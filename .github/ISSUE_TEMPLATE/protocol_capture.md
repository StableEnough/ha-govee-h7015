---
name: Protocol Capture
about: Report captured BLE protocol bytes for the H7015
title: "[PROTOCOL] "
labels: protocol
assignees: ''
---

## What did you capture?
Which Govee app action did you capture the BLE packets for?

- [ ] Per-bulb segment color
- [ ] Warm/cold white color temperature
- [ ] DIY mode
- [ ] Scene mode not in our list
- [ ] Other: ________

## Capture method
- Android HCI snoop log
- nRF Connect
- Wireshark + nRF sniffer
- Other: ________

## Packets
Paste the extracted packets here (hex format, one per line):
```
aa010000000000000000000000000000000000ab  ← keepalive example
3301010000000000000000000000000000000033  ← power on example
```

## What the Govee app showed
Describe what the app displayed when these packets were sent (e.g. "set bulb 3 to blue").

## Analysis
If you ran `analyze_hci.py`, paste the output here.
