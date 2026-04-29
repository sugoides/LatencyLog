# Nmap Trace Monitor

A production-ready Python GUI application to monitor and track nmap traceroute results over time.

## Features
- **Real-time Monitoring**: Automatically runs nmap traces for configured servers.
- **Visual Analytics**: Interactive graphs showing latency trends.
- **Historical Data**: Full history of traces and hop-by-hop details.
- **Site Filtering**: Easily switch between different sites/projects.
- **Database Backend**: All results are stored in a local SQLite database for persistence.

## Prerequisites
- Python 3.8+
- Nmap (must be in your PATH)

## Installation
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
1. Configure your servers in `servers.csv`.
2. Set your `CURRENT_SITE` in `.env` (optional, can be changed in GUI).
3. Run the application:
   ```bash
   python main.py
   ```
   Or use the provided `start.bat`.

## Files
- `main.py`: The GUI application.
- `tracer.py`: The engine that runs nmap and parses output.
- `database.py`: Handles data storage and retrieval.
- `nmap_traces.db`: SQLite database (auto-generated).