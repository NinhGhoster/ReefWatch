# OSINT Sources for Spratly Islands Monitoring

## Twitter/X Accounts to Follow

| Account | Focus | Value |
|---|---|---|
| @detresfa_ | Satellite imagery, military movements | Posts SCS analysis regularly |
| @RALee85 | Defense/military | General military OSINT |
| @IntelSky | Aviation intelligence | Flight tracking, military aviation |
| @TheZone_11 | SCS specifically | South China Sea focused |
| @SCS_PI | South China Sea Probing Initiative | Chinese-language but translates |
| @AsiaMTI | AMTI/CSIS | Official Spratly monitoring |
| @CovertShores | Naval/maritime | Naval movements, submarines |
| @WarshipCam | Naval photography | Ship movements |
| @ameliairvine52 | Satellite imagery analyst | SCS construction updates |

## Websites & Databases

### AMTI (Asia Maritime Transparency Initiative)
- **URL:** https://amti.csis.org/
- **What:** Regular satellite imagery of Spratly features
- **Frequency:** Updates on construction, deployments
- **Free:** Yes

### Sentinel Hub EO Browser
- **URL:** https://apps.sentinel-hub.com/eo-browser/
- **What:** Free satellite imagery (Sentinel-1, Sentinel-2)
- **Resolution:** 10m (Sentinel-2), better with SAR (Sentinel-1)
- **How:** Search by coordinates, select date range
- **Free:** Yes (registration required)

### NASA Worldview
- **URL:** https://worldview.earthdata.nasa.gov/
- **What:** Daily global satellite snapshots
- **Resolution:** ~250m (MODIS), 375m (VIIRS) — coarse but daily
- **Free:** Yes

### Planet Labs Explorer
- **URL:** https://www.planet.com/
- **What:** 3-5m resolution, daily coverage
- **Free:** Limited trial, paid subscriptions
- **Best for:** Detecting aircraft on runways

### MarineTraffic
- **URL:** https://www.marinetraffic.com/
- **What:** Ship tracking (AIS)
- **Use:** Monitor ships near Spratly features — could indicate military activity
- **Free:** Basic, paid for full history

## Telegram Channels

- Search "South China Sea" or "SCS monitoring" on Telegram
- Various OSINT groups share satellite imagery and analysis
- Some military-focused channels track deployments

## Government & Academic Sources

### CSIS AMTI Reports
- Regular reports on island construction, military deployments
- https://amti.csis.org/category/reports/

### IISS (International Institute for Strategic Studies)
- Military balance reports, Asia-Pacific focus

### RAND Corporation
- South China Sea strategic analysis

### Lowy Institute (Australia)
- Asia maritime security research

### USNI News (US Naval Institute)
- Naval deployments, US Navy movements in SCS

## Automated Monitoring Ideas

### Satellite Imagery Alerts
- Planet Labs has API for automated change detection
- Can set up alerts when new imagery is available for specific coordinates

### Twitter/X Monitoring
- Use RSS feeds or Twitter API to monitor key accounts
- Filter for keywords: "Spratly", "Fiery Cross", "Subi Reef", "Mischief Reef", "SCS"

### MarineTraffic Alerts
- Set up area alerts for ship movements near Spratly features
- Can detect unusual naval deployments

### OpenSky Automated Sweep
- See opensky_sweep.py in this directory
- Pings OpenSky every 15 minutes, logs any aircraft detected

## Quick Check Routine

**Daily (5 min):**
1. Check @detresfa_ on Twitter for new satellite imagery
2. Run `python3 opensky_once.py` for any ADS-B detections

**Weekly (15 min):**
1. Check AMTI for new reports
2. Check Sentinel Hub for new cloud-free imagery
3. Review opensky_sweep.py logs for detections

**Monthly (30 min):**
1. Review Planet Labs if subscribed
2. Check IISS/RAND for new analysis papers
3. Update monitoring approach based on findings
