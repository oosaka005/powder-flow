# Raspberry Pi deployment

1. Use the existing repository at `/home/sdl-5/powder-flow` and its `.venv`.
   After pulling an update, install `requirements.txt` into that environment.
2. Keep the existing Balance Server deployment and set its endpoint in
   `/etc/powder-flow.env`. Do not launch the formulation-cell powder dispenser
   server for the same Motor Bonnet.
3. Copy `powder-flow.env.example` to `/etc/powder-flow.env` and adjust hosts or
   ports if required. Do not put I2C addresses in this file.
4. Copy the units in `systemd/` to `/etc/systemd/system/`, then enable
   `powder-flow.target`. Enable `powder-flow-kiosk.service` only on an RPi with a
   local display and Chromium installed.
5. Confirm the first-layer server states, then open
   `http://dispensercontroller.local:8000` from a laptop.

The service account needs access to I2C, GPIO, camera, and the existing
configuration/log/output paths. Only the dispenser server process may own the
Motor Bonnet; it also takes an inter-process lock at
`/tmp/powder-characterizer-dispenser.lock` by default.
