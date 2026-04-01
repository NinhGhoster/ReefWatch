# Ship-Based ADS-B Receiver Setup Guide
# For monitoring aircraft near the Spratly Islands

## Hardware Shopping List

| Item | Est. Cost | Notes |
|---|---|---|
| RTL-SDR Blog V3/V4 dongle | $25-35 | Get from rtl-sdr.com, not Amazon clones |
| 1090 MHz antenna (collinear or spider) | $15-30 | Can DIY a quarter-wave spider for ~$5 |
| Raspberry Pi 4 (4GB+) | $60 | Pi 3B+ works too, Pi 4 preferred |
| MicroSD card (32GB+) | $10 | For OS and logs |
| USB power bank (20,000 mAh) | $20-30 | If no ship power available |
| Waterproof enclosure | $15 | For the outdoor antenna |
| Coax cable + adapters (SMA) | $10-15 | Connect antenna to dongle |
| **Total** | **~$155-195** | |

## Software Setup

### 1. Install Raspberry Pi OS
Flash Raspberry Pi OS Lite (64-bit) to SD card.

### 2. Install dump1090-fa
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y git build-essential pkg-config libusb-1.0-0-dev lighttpd

# Install dump1090-fa
git clone https://github.com/flightaware/dump1090.git
cd dump1090
make
sudo make install

# Or use the PiAware package (easier)
sudo apt install -y piaware
# This installs dump1090-fa automatically
```

### 3. Install tar1090 (better web interface)
```bash
sudo bash -c "$(wget -nv -O - https://raw.githubusercontent.com/wiedehopf/tar1090/master/install.sh)"
```

### 4. Configure
```bash
# Set RTL-SDR gain
sudo tee /etc/modprobe.d/rtlsdr-blacklist.conf << 'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF

# Test the dongle
rtl_test -t
```

### 5. Set up data forwarding (optional)
To send data to a remote server instead of local storage:

```bash
# Option A: Feed to your own server
# In dump1090 config, set --net-ro-port and forward via netcat/ssh

# Option B: Feed to FR24/FlightAware (get free premium access)
# Signup at:
# - flightradar24.com/share-your-data
# - flightaware.com/adsb/piaware/
```

### 6. Auto-start on boot
```bash
sudo systemctl enable dump1090-fa
sudo systemctl start dump1090-fa
```

## Antenna Placement

- **Height matters most** — higher = more range
- Mount on mast above ship cabin/railing
- Keep clear of metal obstructions
- At ship deck level: ~100-150 km range
- On a 5m mast: ~200-300 km range
- At bridge height on a large vessel: ~300-400 km range

## Range Calculator

```
Range (km) ≈ 3.57 × √(antenna_height_m)
```
- 2m height → ~5 km (bad, need to go higher)
- 10m height → ~11 km (still poor)
- Sea level + elevated aircraft (10,000m altitude) → ~400 km theoretical max

For aircraft at altitude, range is mainly limited by Earth curvature, not your antenna height.

## Data Storage

```bash
# Log all aircraft to JSON
dump1090-fa --net --net-ro-port 30002 --write-json /var/www/html/dump1090/data

# Or pipe to your own logger
nc localhost 30002 | while read line; do
  echo "$(date -Iseconds) $line" >> /var/log/adsb/raw.log
done
```

## Expected Coverage at Spratlys

| Location | Distance from nearest receiver | Coverage? |
|---|---|---|
| Fiery Cross (China) | ~400+ km from any coast | Unlikely without ship |
| Subi Reef (China) | ~400+ km | Same |
| Mischief Reef (China) | ~300+ km | Same |
| Taiping (Taiwan) | ~400+ km | Same |
| Layang-Layang (Malaysia) | ~300 km from Sabah | Possible with high-gain antenna |

**Best strategy:** Position a ship ~100-200 km from Fiery Cross Reef. Even at deck level, you'd cover the entire cluster of Chinese-built islands.

## Ship Options

1. **Charter a fishing boat** from Sabah (Malaysia) — Layang-Layang is a dive resort, boats go there regularly
2. **Commercial vessel** — if you know anyone on cargo ships transiting the SCS
3. **Research vessel** — universities sometimes do SCS research with available berths
4. **Yacht** — if you have access, sailing the SCS is legal (contested waters, be careful)

## Legal Note

ADS-B reception is legal in international waters. The data is broadcast openly by aircraft. However:
- Don't enter territorial waters of disputed claims without research
- Some countries (China) may object to monitoring military activity
- Stay in international waters or Malaysian/Philippine waters to be safe
