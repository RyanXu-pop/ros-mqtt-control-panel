# ROS MQTT Robot Control Panel

Desktop control panel for a mobile robot system, built with PySide6 and designed around MQTT, ROS 2 bridging, SSH-based robot process control, map visualization, telemetry, pose setting, navigation, patrol, and inspection workflows.

This repository is a public review version prepared for admissions review. It keeps the application source, tests, example configuration, maps, and ROS bridge code, while excluding private configuration, virtual environments, cached files, logs, local task state, and old Git history.

## Highlights

- PySide6 desktop UI for robot monitoring and command workflows.
- MQTT message flow for goals, poses, status, voltage, maps, scans, odometry, paths, and velocity commands.
- ROS 2 bridge node for translating between robot-side ROS topics and MQTT topics.
- SSH management layer for remote robot startup, process control, and map synchronization.
- Map display with navigation goals, initial pose setting, scan overlays, and path visualization.
- Patrol and inspection-plan controllers with test coverage.
- Mock robot, mock LiDAR, and workflow tests for development without full hardware access.

## Architecture

```text
Desktop UI
  -> Controllers and state hub
  -> MQTT client
  -> ROS 2 MQTT bridge on robot side
  -> ROS navigation stack / robot sensors

Desktop UI
  -> SSH manager
  -> Remote process and map synchronization
```

## Repository Layout

```text
.
|-- main.py                  # Application entry point
|-- config/                  # Public example configuration
|-- src/core/                # Shared models, constants, utilities
|-- src/controllers/         # Navigation, patrol, pose, workflow controllers
|-- src/network/             # MQTT and SSH integration
|-- src/ui/                  # Earlier UI modules
|-- src/ui_v2/               # Current UI layout, panels, map view, theme
|-- ros/                     # ROS 2 MQTT bridge
|-- scripts/                 # Local mock and setup utilities
|-- maps/                    # Example map assets
`-- tests/                   # Unit and workflow tests
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item config\config.example.yaml config\config.yaml
python main.py
```

Edit `config/config.yaml` for your local robot IP, MQTT broker, SSH username, and topic names. Do not commit the local `config.yaml`.

## Robot-Side Bridge

The ROS bridge lives in `ros/mqtt_bridge_ros2.py`. It is intended to run on the robot side and mirror selected ROS 2 topics through MQTT so the desktop UI can monitor and command the robot.

## Tests

```powershell
python -m pytest tests
```

Some tests use mocks for MQTT, robot state, and UI workflows. Full hardware validation requires a robot, MQTT broker, and ROS 2 environment.

## Public Release Notes

Excluded from this version:

- private `config.yaml`
- `.git` history copied from older working folders
- virtual environments and Python caches
- logs, local task state, and generated outputs
- packaged wheels and other local dependency artifacts
