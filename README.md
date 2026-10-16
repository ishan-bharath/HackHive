# Honeywell HackHive — PS4

## Problem
Joint optimization of control-panel placement, room assignment, and closed-loop cable routing.

## Current Progress
- Inspected the ResPlan floor-plan dataset.
- Extracted candidate room-passage relationships.
- Developed diagnostics for doorway geometry and passage connectivity.
- Implemented experimental obstacle-aware and portal-aware routing prototypes.
- Generated route visualizations and structured JSON diagnostics.

## Current Limitations
- Candidate passages are not yet physically verified.
- Cable routes are experimental and may cross walls or violate room boundaries.
- Closed-loop cable routing is not implemented.
- Joint optimization of panel placement, room assignments, and cable routing is not implemented.
- Area calibration and panel-capacity enforcement remain incomplete.

## Development Approach
1. Validate room, wall, and doorway geometry.
2. Implement physically constrained portal-aware routing.
3. Construct and validate closed cable loops.
4. Jointly optimize panel placement, room assignment, and cable routing.
5. Compare results against a baseline using measurable metrics.

## Data and Dependencies
The ResPlan dataset is not included in this repository. Scripts currently rely on a local dataset installation and may require environment-specific path configuration.

## Status
Research and prototyping. Results are not yet validated for physical installation or code compliance.
