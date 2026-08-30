FX M1 Bot V6.9

Changes in V6.9:
- Notification rebuilt again with custom compact content: signal + market/server/MT5 + PAUSE and EMERGENCY buttons directly on the normal notification card when the Android shell permits custom foreground layouts.
- Expanded notification keeps balance, positions, risk/AUTO, signal quality, API price and last analysis.
- New V6.9 notification channel so old OEM/channel settings do not carry over.
- Server input now shows a fixed http:// prefix. Enter only e.g. 192.168.1.8:8000.
- Server editor auto-scrolls above the keyboard; Activity uses adjustResize.
- MARKET STATUS now uses an automatically calculated weekly FX session based on America/New_York with DST conversion to Asia/Tashkent.
  Closed: weekend interval from Friday 16:59 NY to Sunday 17:05 NY.
  Open: trading week from Sunday 17:05 NY to Friday 16:59 NY.
- Removed the redundant "Sunday closed all day" line. Dates roll automatically every week/month/year.
- Stronger approved dark cosmic purple/blue background.
- Existing monitoring, signals, API key flow, AUTO trading, MT5 bridge, risk controls, positions and journal retained.

Bridge: unchanged.
