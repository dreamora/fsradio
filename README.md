# fsradio

fsradio is a graphical frontend for controlling Frontier Silicon / SmartRadio based internet radios on \*nix platforms. It provides a simple GUI to browse stations, control playback, and manage presets via your local network.

## Features

- Discover and connect to Frontier Silicon / SmartRadio devices
- Browse available radio stations and genres
- Play, pause, and stop radio streams
- Manage and select presets
- Adjust volume and mute
- Display current station information

## Requirements

- Python 3.x
- Python TKinter (for GUI)
- Network access to your Frontier Silicon / SmartRadio device

## Installation

1. Clone this repository:

```sh
git clone https://github.com/dreamora/fsradio.git
cd fsradio
```

2. Install dependencies:

```sh
./install.sh
```

## Usage

Run the GUI application:

`./start.sh`

or

```sh
venv/bin/python3 fsradio_gui.py
```

## References and dependencies

- [AFSAPI](https://github.com/zhelev/python-afsapi)
