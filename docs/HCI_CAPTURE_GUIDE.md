# H7015 HCI Capture Guide

This guide walks you through capturing the H7015's Bluetooth packets so you
can fill in the protocol gaps (per-bulb segments, warm-white encoding, DIY mode).

## What You'll Need

- An Android phone with the Govee Home app installed
- A computer with `adb` (Android Debug Bridge) installed
- A USB cable to connect your phone to the computer
- The H7015 powered on and paired with the Govee app

## Step-by-Step

### 1. Enable Bluetooth HCI Snoop Log on Android

1. On your phone: **Settings → About phone**
2. Tap **Build number** 7 times to enable Developer Options
3. Go to **Settings → System → Developer options**
4. Enable **Bluetooth HCI snoop log**
5. Toggle Bluetooth OFF then ON

### 2. Capture Traffic

1. Start a screen recording on your phone (so you can correlate timestamps later)
2. Open the Govee Home app and connect to your H7015
3. Perform the actions you want to capture — **do each one slowly (2-3 seconds apart)**:

**For per-bulb segments:**
- [ ] Set bulb 1 to red
- [ ] Set bulb 1 to green
- [ ] Set bulb 1 to blue
- [ ] Set bulb 2 to red
- [ ] Set bulb 8 to red
- [ ] Set bulb 9 to red
- [ ] Set bulb 15 to red
- [ ] Set all bulbs to different colors

**For warm/cold white:**
- [ ] Set color temperature to warmest (2000K)
- [ ] Set color temperature to coldest (6500K)
- [ ] Set color temperature to middle

**For DIY mode:**
- [ ] Create a DIY with 2 colors, fade style, speed 50%
- [ ] Create a DIY with 4 colors, jumping style, speed 100%

**For scenes:**
- [ ] Activate scene 1 (Sunrise)
- [ ] Activate scene 2 (Sunset)
- [ ] Try any scenes not in our list

4. Stop the screen recording
5. Toggle Bluetooth OFF then ON (flushes the log)

### 3. Pull the Log

```bash
# Generate a bug report (contains the HCI log)
adb bugreport h7015_bugreport

# Unzip it
unzip h7015_bugreport.zip -d h7015_bugreport

# Find the HCI log
# On newer Android (10+):
ls h7015_bugreport/FS/data/misc/bluetooth/logs/*.cfa

# On older Android:
ls h7015_bugreport/FS/data/log/bt/btsnoop_hci.log
```

### 4. Analyze the Log

```bash
# Install the analyzer
uv sync --extra analyze

# Run the analyzer (filter to your H7015's MAC)
uv run python standalone/analyze_hci.py \
    h7015_bugreport/FS/data/misc/bluetooth/logs/btsnoop_hci.log \
    --mac AABBCCDDEEFF \
    --govee-only

# Save as JSON for further analysis
uv run python standalone/analyze_hci.py \
    h7015_bugreport/FS/data/misc/bluetooth/logs/btsnoop_hci.log \
    --mac AABBCCDDEEFF \
    --json packets.json
```

### 5. Interpret the Results

The analyzer will show:
- **Summary**: total packets, by type (write/read/notify)
- **Govee packets**: by kind (command/keepalive/DIY)
- **Distinct commands**: each unique command with its label

Look for patterns:
- `33 05 0B` = segment command — note bytes 6-7 (left/right bitmask)
- `33 05 02` with byte 6 = `01` = color temperature — note bytes 7-8 (warm/cold)
- `A1 02` = DIY mode — note the multi-packet sequence

### 6. Report Your Findings

Open a GitHub issue using the **Protocol Capture** template and paste:
- The analyzer output
- Which Govee app actions correspond to which packets
- Your H7015's MAC address (or just the last 4 digits for privacy)

## Tips

- **Be slow and deliberate** — wait 2-3 seconds between each action so packets don't overlap
- **One thing at a time** — don't change settings while a scene is transitioning
- **Keep the phone close** to the H7015 to avoid BLE retransmits cluttering the log
- **Record your screen** — the timestamps let you match packets to app actions
- **Use nRF Connect** as an alternative — it can log BLE traffic directly without adb
