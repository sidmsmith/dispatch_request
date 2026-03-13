# Manual Dispatch Request (`dispatch_request`)

`dispatch_request` is a web app used to manually create Transportation Orders (TOs) in Manhattan TMS.

It reuses the same auth and theming approach as the `dispatch` app, then guides users through:
- selecting terminal and facilities,
- defining one or more delivery stops,
- entering product line details,
- and submitting a TO creation request.

## Current Version

- App label in UI: `Manual Dispatch Request v1.0.0`

## Key Features

- URL-aware auth support:
  - accepts `ORG` or `Organization` query parameter.
- Theme support:
  - `Light`, `Dark`, `Manhattan`, `Love's`, `Rockline`, `Hy-Vee`.
- Master-data-driven dropdowns:
  - Terminals and Facilities from Facility Master.
  - Product Class from Item Master.
  - Driver/Tractor/Trailer type defaults from Asset Manager by selected terminal.
- Multi-stop request entry:
  - add/remove stops,
  - add/remove product lines per stop,
  - drag and drop stop reorder.
- Product defaults:
  - Average Weight (lbs) default by Product Class.
  - Average Cube (cu ft) default by Product Class.
- Local persistence:
  - all non-date values are auto-saved to `localStorage` and restored on refresh.
- Validation-first submit:
  - blocks submit until required data and date sequencing are valid.

## Screen Flow

1. User authenticates with ORG.
2. Main form loads with terminals/facilities/product classes.
3. User enters request data and submits.
4. Backend:
   - gets next-up TO number,
   - builds TO payload,
   - creates TO,
   - returns success/error message.

## API Flow

### 1) Authentication
- Endpoint: `POST /api/auth`
- Request payload:
  - `org`
- Result:
  - OAuth token is returned and stored in memory by the UI for the current session.

### 2) Main Screen Data

#### Facilities and terminals
- Endpoint: `POST /api/facilities`
- Backend source API: `POST /facility/api/facility/facility/search`
- Pulled facility fields (minimal searchable/display set):
  - `FacilityId`
  - `FacilityName`
  - `Description`
  - `FacilityTypeTerminal`
  - `IsActive`
  - `FacilityAddress.City`
  - `FacilityAddress.State`
  - `FacilityAddress.PostalCode`
  - `FacilityAddress.Country`
- Terminal list uses:
  - `Query: "FacilityTypeTerminal = 'true' AND IsActive = 'true'"`

#### Product classes
- Endpoint: `POST /api/product_classes`
- Backend source API: `POST /item-master/api/item-master/productClass/search`
- Display behavior:
  - Prefer normalized `Description`
  - Fall back to `ProductClassId`
  - Alphabetically sorted

#### Terminal defaults
- Endpoint: `POST /api/terminal_resource_defaults`
- Backend source APIs:
  - Asset Manager driver/tractor/trailer searches
  - Driver type and equipment type lookups
- Used to populate optional Driver/Tractor/Trailer dropdowns after terminal selection.

### 3) Submit Request (end-to-end orchestration)
- Endpoint: `POST /api/submit_request`
- This endpoint orchestrates three business creation steps:
  1. Create Transportation Orders (one TO per stop)
  2. Create Shipment from those TOs
  3. Create Trip from the Shipment

---

## Detailed Creation APIs

### A) Transportation Order creation

#### NextUp (TO IDs)
- URL: `GET /routing/api/nextup/getNextupNumbersByCounterType?counterTypeId=TransportationOrderId&count={stopCount}`
- Purpose:
  - Fetches one TO ID per delivery stop in a single call.

#### Create TO (one call per stop)
- URL: `POST /routing/api/routing/transportationOrder`
- Header-level fields used:
  - `TransportationOrderId`
  - `OrderTypeId` (optional passthrough)
  - `OriginFacilityId`
  - `DestinationFacilityId` (stop destination)
  - `PickupStartDateTime`
  - `PickupEndDateTime`
  - `DeliveryStartDateTime`
  - `DeliveryEndDateTime`
  - `PlanningTypeId` (default `Outbound`)
  - `ToPlanningStatusId` (default `1000`)
  - `PrePlanTransportation` (`false`)
- Line-level fields used:
  - `TransportationOrderLineId`
  - `TransportationOrderId`
  - `DestinationFacilityId` (kept aligned to header destination)
  - `ProductClassId`
  - `OrderedQuantity` (pallet count)
  - `QuantityUomId` (`pallet`)
  - `ExtendedWeight` = `pallets * avgWeight`
  - `ExtendedVolume` = `pallets * avgCube`
  - `WeightUomId` (`lb`)
  - `VolumeUomId` (`cuft`)
  - pickup/delivery date windows

### B) Shipment creation

#### NextUp (Shipment ID)
- URL: `GET /shipment/api/nextup/getNextupNumbersByCounterType?counterTypeId=NEWSHIPMENT&count=1`
- Purpose:
  - Returns one shipment ID (example format: `SHIP000000123`).

#### Create Shipment
- URL: `POST /shipment/api/shipment/shipment/importShipmentWithOrders`
- Header-level fields used:
  - `ShipmentId` (from NEWSHIPMENT NextUp)
  - `ModeId` (`TL`)
  - `CarrierId` (`PFLT`)
  - `DesignatedCarrierId` (`PFLT`)
  - `OrderCreationType` (`TransportationOrder`)
  - `ExternalShipmentWithTO` (`true`)
  - `ExternallyPlanned` (`true`)
  - `PlanningStatusId.PlanningStatusId` (`0500`)
  - `Actions.Order` (`RESET`)
  - `Actions.Stop` (`RESET`)
- Stop construction logic:
  - Stop 1:
    - `StopActionId.StopActionId = PU`
    - `FacilityId = OriginFacilityId`
    - `StopOrder = all created TO IDs`
    - `PlannedArrivalDateTime = pickupStart`
    - `PlannedDepartureDateTime = pickupEnd`
  - Stops 2..N:
    - grouped by destination facility in first-seen order
    - `StopActionId.StopActionId = DL`
    - each stop contains TO IDs for that destination in `StopOrder`
    - `PlannedArrivalDateTime = deliveryStart || deliveryEnd`
    - `PlannedDepartureDateTime = deliveryEnd || deliveryStart`

### C) Trip creation
- URL: `POST /shipment/api/shipment/createTripFromShipments`
- Payload:
  - array with one item:
    - `TripId: null`
    - `ShipmentId: <created shipment id>`
    - `DispatchFlow: true`
- Response handling:
  - Supports both common shapes:
    - `data.ShipmentPlanningAttributes.TripId`
    - `data.TripId` (string or array)
  - Includes retry/fallback behavior to reduce false negatives on optimistic lock timing:
    - retry trip-create attempts
    - shipment lookup fallback for `TripId`

---

## Facility Search (Origin/Delivery)

Facility dropdowns are populated once (startup load), then searched client-side in memory.

### Search input behavior
- Origin and each Delivery stop has:
  - facility dropdown
  - search textbox + magnifier action
  - results count text (`Results: X`)
- Search runs on:
  - click magnifier
  - Enter key in search box

### Search fields matched
Search text is matched against:
- `FacilityId`
- `FacilityName`
- `Description`
- `City`
- `State`
- `PostalCode`
- `Country`

### Recent chips behavior
- Origin and Delivery maintain separate recent lists in localStorage:
  - `dispatch_request_recent_origin_facility_ids_v1`
  - `dispatch_request_recent_delivery_facility_ids_v1`
- Up to 3 chips shown per scope.
- Chips are intentionally resequenced only on submit (not during live edits).

## Form Behavior and Defaults

### Header/Theme
- Theme is saved in `localStorage` key:
  - `dispatch_request_theme`
- URL behavior:
  - `Theme=N` or `theme=N` hides the gear/theme picker
  - `ThemePicker=<theme>` can force startup theme (supports friendly values, case-insensitive)
    - examples: `manhattan`, `Hy-Vee`, `Rockline Industries`, `Love's Travel Stops`

### Date Fields
- Pickup/Delivery date fields are auto-defaulted at runtime.
- Dates are required for submit.
- Required sequencing:
  - Pickup End > Pickup Start
  - Delivery Start > Pickup End
  - Delivery End > Delivery Start

### Stops and Product Lines
- At least one stop is required.
- At least one product line per stop is required.
- Product line fields:
  - Product Class (required)
  - Average Weight (lbs) (must be > 0)
  - Average Cube (cu ft) (must be > 0)
  - Number of Pallets (must be >= 0; TO line requires > 0)

### Product Class Defaults
- Average Weight and Average Cube are auto-populated by Product Class lookup tables.
- If no match exists, default is `0` and user must enter a value > 0.

### Local Storage
- Form state key:
  - `dispatch_request_form_state_v1`
- Saved values include:
  - terminal, origin, selected type fields,
  - stop structure and product lines (class, avg weight, avg cube, pallets).
- Save timing:
  - form state saves on submit (not realtime while editing).
- Dates are intentionally not persisted and continue to use runtime defaults.

## TO Payload Notes

For each TO line:
- `OrderedQuantity` = pallets
- `ExtendedWeight` = pallets * avgWeight
- `ExtendedVolume` = pallets * avgCube
- `WeightUomId` = `lb`
- `VolumeUomId` = `cuft`

## Debug Logging (F12 Console)

The UI logs detailed request/response debug for creation steps:
- TO create payloads + responses (per stop)
- Shipment create payload + response
- Trip create payload + response (including retries/fallback checks)

This helps troubleshoot partial-success flows where TO/Shipment may exist even if Trip creation reports an error.

## Project Structure

- `public/index.html` - UI, styling, form logic, validation, drag/drop, local storage.
- `api/index.py` - Flask backend endpoints and Manhattan API integration.
- `vercel.json` - Vercel routing/build config.
- `server.js` - static file server support.

## Run Locally

### Backend
- Python dependencies:
  - `flask`
  - `requests`

Install and run:

```bash
pip install -r requirements.txt
python api/index.py
```

### Frontend
Serve static files (or run via Vercel/local wrapper):

```bash
node server.js
```

## Deployment

Designed for Vercel with:
- Python API handlers in `api/`
- static frontend in `public/`

## Notes for Future Enhancements

- Add a dedicated login/user profile for known DriverCode context.
- Add server-side product master logic for cube/weight governance.
- Add optional admin tools for updating default product class tables without code changes.
