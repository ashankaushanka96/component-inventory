# Component Inventory

## Overview

The **Component Inventory** is a comprehensive solution for managing and monitoring components in a system. It provides functionalities for detecting, fetching, and searching components, along with managing server details.

## Features

- **Component Detection**: Automatically detects components in specified directories.
- **Component Fetching**: Fetches components from remote sources.
- **Component Searching**: Searches for components based on specified criteria.
- **Server Details Management**: Manages server configurations and details.

## Prerequisites

- Python 3.9+
- Required Python packages:
  - `mysql-connector-python` (for database connections)
  - `prettytable` (for displaying data in tables)
  - `paramiko` (for SSH connections)
  - `boto3` (for AWS integration)
  - `loguru` (for logging)

## Configuration

### File Structure

```bash
├── componentDetector.py  # Detects components in a specified directory
├── componentFetcher.py    # Fetches components from a remote source
├── componentSearcher.py    # Searches for components based on criteria
├── ServerDetailsManager.py  # Manages server details and configurations
└── search.sh              # Shell script to facilitate running searches
```

### Example Config

```yaml
aws:
  regions:
    us-east-1:
      key_path: "keys/US.pem"
    ap-southeast-1:
      key_path: "keys/AP.pem"
    eu-west-1:
      key_path: "keys/EU.pem"

datacenters:
  dc1:
    ips:
      - "DC_1_IP_1"
      - "DC_1_IP_2"
    key_path: "keys/DC_1.pem"
    user: "datacenter1"
  dc2:
    ips:
      - "DC_2_IP_1"
      - "DC_2_IP_2"
    key_path: "keys/DC_2.pem"
    user: "datacenter2"

db_config:
  user: <db_username>
  password: <db_password>
  host: <db_ip>
  database: <db_name>
```

## Monitoring Metrics

### The component tracks the following metrics:

- Component detection status
- Fetching success rates
- Search query performance

## Security Considerations

- Ensure proper handling of sensitive information, especially when dealing with database connections and AWS credentials.
- Regularly review logs for any anomalies.
