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
- App then stores token in memory for session API calls.

### 2) Main Screen Data
- Facilities/terminals: `POST /api/facilities`
  - Terminal query filters for active terminals.
- Product classes: `POST /api/product_classes`
  - Display uses normalized Description; falls back to ProductClassId.
- Terminal resource defaults: `POST /api/terminal_resource_defaults`
  - Loads Driver/Tractor/Trailer type options and marks defaults.

### 3) Submit Request
- Endpoint: `POST /api/submit_request`
- Backend sequence:
  1. `GET /routing/api/nextup/getNextupNumbersByCounterType?counterTypeId=TransportationOrderId&count=1`
  2. Build Transportation Order payload
  3. `POST /routing/api/routing/transportationOrder`

If NextUp is unavailable, submit is blocked with:
- `No NextUp Transportation Order counter is configured in this environment.`

## Form Behavior and Defaults

### Header/Theme
- Theme is saved in `localStorage` key:
  - `dispatch_request_theme`

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
- Dates are intentionally not persisted and continue to use runtime defaults.

## TO Payload Notes

For each TO line:
- `OrderedQuantity` = pallets
- `ExtendedWeight` = pallets * avgWeight
- `ExtendedVolume` = pallets * avgCube
- `WeightUomId` = `lb`
- `VolumeUomId` = `cuft`

## Debug Logging (F12 Console)

For TO creation debugging only, the UI logs:
- the POST payload sent to `/routing/api/routing/transportationOrder`
- the full create response (status + JSON/text)

No extra F12 logging is added for auth, lookups, or NextUp calls.

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
