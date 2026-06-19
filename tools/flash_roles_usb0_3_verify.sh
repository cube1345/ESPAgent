#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export ESPAGENT_FLASH_BAUD="${ESPAGENT_FLASH_BAUD:-115200}"

echo "==> Flashing ESPAgent roles on /dev/ttyUSB0-3"
echo "    USB0 coordinator_agent"
echo "    USB1 sensor_agent"
echo "    USB2 control_agent"
echo "    USB3 guardian_agent"
echo "    baud ${ESPAGENT_FLASH_BAUD}"

bash "${ROOT_DIR}/tools/flash_roles_usb0_3.sh"

echo
echo "==> Waiting for ttyUSB0-3 to re-enumerate"
for _ in $(seq 1 30); do
  if [[ -e /dev/ttyUSB0 && -e /dev/ttyUSB1 && -e /dev/ttyUSB2 && -e /dev/ttyUSB3 ]]; then
    break
  fi
  sleep 1
done

echo
echo "==> Verifying ESPAgent role identities"
python3 "${ROOT_DIR}/tools/verify_roles_usb0_3.py" --echo
