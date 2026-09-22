# Powder Characterizer SiLA 2 migration notes

## Preserved contracts

- `operation/workflows.py`, calculation thresholds, retry counts, density and
  repose classifications, and motor-operation ordering remain the application
  source of truth.
- `config/app_settings.json` and every existing result/Material DB key remain
  unchanged. Endpoint configuration is environment-only.
- The Web UI Gateway talks only to `PowderCharacterizer`; the second layer talks
  to the dispenser, existing balance, and camera SiLA 2 servers.
- Generated SiLA 2 files are produced from the three FDL files and are not
  hand-edited.

## Deliberate corrections and decisions

- I2C discovery has no configured address and no hard-coded candidate range.
  The full bus scan is used; `0x70` is removed as PCA9685 All Call, one remaining
  individual address is accepted, and multiple addresses are an ambiguity fault.
  Unavailable, ambiguous, cancelled, and hardware-fault outcomes are declared in
  the FDL as SiLA Defined Execution Errors instead of leaking generic gRPC errors.
- The current powder-flow driver runs the auger forward in `vib_with_aug` and
  `run_all_motors`. The formulation-cell reference driver runs it in reverse.
  The current powder-flow direction is preserved because this migration must not
  change motor behavior.
- The existing Balance Server defaults to port `50052`, so new defaults avoid
  that and the other ports in the reference `servers.toml`: dispenser `50063`,
  camera `50064`, characterizer `50065`, Web UI `8000`.
- Formal images travel as SiLA `Binary`, which uses the library's binary transfer
  facility rather than embedding the image in a normal gRPC message. Bytes are
  not re-encoded by either server.

## Known hardware-verification item

The old in-process balance driver waits 2 seconds before sending `T`, then waits
1 second after it. The reused Balance Server sends `T` immediately and waits 1.5
seconds. `ReadWeight` has the same 2-second pre-read settling time. No compensating
delay or new stability algorithm was added because that would change measurement
behavior without physical validation. The Tare timing difference must be checked
from the Web UI on the real balance and its impact recorded before acceptance.

## Acceptance boundary

Fake-device regression tests and an in-process two-layer SiLA 2 manual-operation
test have been run. Raspberry Pi GPIO/I2C/camera, I2C interruption recovery, the
real Balance Server, network access from another laptop, kiosk startup, and all
real experiments remain hardware acceptance work and must be executed from the
new Web UI, not PySide.
