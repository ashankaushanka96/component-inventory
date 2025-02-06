import os
import paramiko
import mysql.connector
import json
import yaml
import re
from datetime import datetime
from loguru import logger

class ComponentFetcher:
    def __init__(self, config_file):
        # Load configuration from YAML file
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)

        # AWS Regions and Datacenter configurations
        self.regions = config['aws']['regions']
        self.datacenters = config['datacenters']
        
        # Database connection setup
        self.db_config = config['db_config']
        self.db_connection = mysql.connector.connect(**self.db_config)
        self.cursor = self.db_connection.cursor()
        
        # Path to the local and remote script
        self.local_script_path = 'componentDetector.py'
        self.remote_script_path = '/tmp/componentDetector.py'
        self.use_sudo = True
        self.script_directory = os.path.dirname(os.path.abspath(__file__))

        # Set up logging
        log_file_path = os.path.join(self.script_directory, './logs/component_fetcher_{time:YYYYMMDDHHmmss}.log')
        logger.add(
            log_file_path, 
            rotation="1 day",
            retention="2 days",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {message}"
        )


    def get_valid_servers(self):
        try:
            # Fetch servers, prioritizing those with failures first
            all_regions = []
            if self.regions:
                all_regions = all_regions + list(self.regions.keys()) 
            if self.datacenters:
                all_regions = all_regions + list(self.datacenters.keys())
            placeholders = ', '.join(['%s'] * len(all_regions))
            query = f"""
                SELECT server_ip, user, search_path, region, update_status
                FROM servers
                WHERE user IS NOT NULL
                AND region IN ({placeholders})
                AND running_state = 'running'
                ORDER BY 
                    CASE WHEN update_status = 'failure' THEN 0 ELSE 1 END,
                    last_updated_time ASC
            """

            self.cursor.execute(query, tuple(all_regions))
            servers = [
                {'ip': row[0], 'user': row[1], 'search_path': row[2], 'region': row[3], 'update_status': row[4]} 
                for row in self.cursor.fetchall()
            ]
            logger.info(f"Fetched {len(servers)} valid servers from the database with failure instances prioritized.")
            return servers
        except Exception as e:
            logger.error(f"Error fetching servers: {e}")
            return []

    def get_python_interpreter(self, ssh_client):
        # Check if python is available
        stdin, stdout, stderr = ssh_client.exec_command('which python')
        python_path = stdout.read().decode('utf-8').strip()
        
        if not python_path:
            # Check if python3 is available
            stdin, stdout, stderr = ssh_client.exec_command('which python3')
            python_path = stdout.read().decode('utf-8').strip()
        
        if python_path:
            logger.info(f"Using Python interpreter: {python_path}")
            return python_path
        else:
            logger.error("No valid Python interpreter found on the server.")
            return None


    def get_components(self, ip, ssh_client, search_path):
        try:
            python_interpreter = self.get_python_interpreter(ssh_client)

            if not python_interpreter:
                self.update_server_status(ip, "Failure", "No valid Python interpreter found on the server.")
                return None

            with open(self.local_script_path, 'r') as script_file:
                script_content = script_file.read()
            
            sftp = ssh_client.open_sftp()
            with sftp.open(self.remote_script_path, 'w') as remote_script:
                remote_script.write(script_content)
            sftp.close()
            
            if self.use_sudo:
                command = f"sudo {python_interpreter} {self.remote_script_path} {search_path}"
            else:
                command = f"{python_interpreter} {self.remote_script_path} {search_path}"

            stdin, stdout, stderr = ssh_client.exec_command(command)
            result = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            # if error:
            #     logger.warning(f"Error from remote script on path {search_path}: {error}")
            #     self.update_server_status(ip, "Failure", f"Error from remote script on path {search_path}: {error}")
            #     return None
            # Use regex to filter out JSON data
            json_match = re.search(r'(\{.*\})', result, re.DOTALL)
            print(json_match)
            if json_match:
                json_result = json_match.group(0)  # Extract the JSON part
                print(json_result)
                try:
                    output = json.loads(json_result)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode JSON output from {search_path}: {e}")
                    self.update_server_status(ip, "Failure", f"Failed to decode JSON output from {search_path}: {e}")

                if output["status"] == "success":
                    components = output["components"]
                    if len(components) == 0:
                        logger.warning(f"No components found on path {search_path}")
                        self.update_server_status(ip, "Success", f"No components found on path {search_path}")
                        return None
                    logger.info(f"Decoded components JSON for path {search_path}: {components}")
                    return components
                    
                else:
                    error_message = output["message"]
                    logger.error(f"Script execution failure, error : {error_message}")
                    self.update_server_status(ip, "Failure", f"Script execution failure, error : {error_message}.")
            else:
                logger.warning(f"No json output from remote script for path {search_path}.")
                self.update_server_status(ip, "Success", f"No json output from remote script for path {search_path}.")
            return None
        except Exception as e:
            logger.error(f"Failed to get components for path {search_path}: {e}")
            self.update_server_status(ip, "Failure", f"Failed to get components for path {search_path}: {e}")
            return None
        
    def delete_exisiting_components(self, ip, region):
        try:
            self.cursor.execute(
            "DELETE FROM components WHERE ip = %s AND region = %s", 
            (ip, region)
            )
        except Exception as e:
            logger.error(f"Error deleting components for IP {ip} in region {region}: {e}")

    def insert_into_database(self, ip, component, region):
        try:
            self.cursor.execute(
                "SELECT 1 FROM components WHERE ip = %s AND component_name = %s AND region = %s", 
                (ip, component['comp_name'], region)
            )
            if self.cursor.fetchone() is None:
                self.cursor.execute(
                    "INSERT INTO components (ip, region, component_name, platform, comp_path) VALUES (%s, %s, %s, %s, %s)",
                    (ip, region, component['comp_name'], component['platform'], component['path'])
                )
                self.db_connection.commit()
                logger.info(f"Inserted component {component['comp_name']} for IP {ip} in region {region}.")
            else:
                logger.info(f"Skipping duplicate entry for IP {ip}, component {component['comp_name']}, and region {region}.")
        except Exception as e:
            logger.error(f"Error inserting component {component['comp_name']} for IP {ip} in region {region}: {e}")

    def update_server_status(self, ip, status, error_message=None):
        try:
            self.cursor.execute(
                "UPDATE servers SET last_updated_time = %s, update_status = %s, error_message = %s WHERE server_ip = %s",
                (datetime.now(), status, error_message, ip)
            )
            self.db_connection.commit()
            logger.info(f"Updated last_updated_time, update_status, and error_message for IP {ip} to '{status}'.")
        except Exception as e:
            logger.error(f"Failed to update server status for IP {ip}: {e}")

    def ssh_connection(self, ip, user, key_path):
        ssh_client = paramiko.SSHClient()
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh_client.connect(hostname=ip, username=user, key_filename=key_path)
            logger.info(f"Connected to {ip} with user {user}.")
            return ssh_client, user
        except Exception as e:
            logger.error(f"Connection with {user} failed on {ip}: {e}")
            self.update_server_status(ip, "Failure", "Connection with {user} failed on {ip}: {e}")
            return None, None
        
    def key_finder(self, region):
        # Determine key path based on AWS or datacenter
        if self.regions:
            if region in self.regions:
                self.use_sudo = True
                return self.regions[region]['key_path']
        if self.datacenters:
            if region in self.datacenters:
                self.use_sudo = False
                return self.datacenters[region]['key_path']
        else:
            return None

    def fetch_and_store_components(self):
        # Fetch only failure instances first
        servers = self.get_valid_servers()
        failure_instances = [server for server in servers if server.get('update_status') == 'Failure']
        success_instances = [server for server in servers if server.get('update_status') != 'Failure']

        # Process failure instances first
        logger.info("Processing failure instances first...")
        self.process_servers(failure_instances)

        # Prompt to continue to success instances
        proceed = input("Failure instances processed. Proceed with success instances? (y/n): ")
        if proceed.lower() == 'y':
            logger.info("Proceeding with success instances...")
            self.process_servers(success_instances)
        else:
            logger.info("User chose not to proceed with success instances.")

    def process_servers(self, servers):
        for server in servers:
            ip = server['ip']
            user = server['user']
            region = server['region']
            
            key_path = self.key_finder(region)
            if key_path is None:
                logger.warning(f"No key path found for region {region}. Skipping server {ip}.")
                self.update_server_status(ip, "Failure", "Missing key path")
                continue

            ssh_client, user = self.ssh_connection(ip, user, key_path)
            if ssh_client is None:
                logger.warning(f"Failed to connect to {ip}. Moving to the next server.")
                continue

            try:
                search_path = server['search_path']
                components = self.get_components(ip, ssh_client, search_path)
                if components:
                    self.delete_exisiting_components(ip, region)
                    for component in components:
                        self.insert_into_database(ip, component, region)
                    
            except Exception as e:
                logger.error(f"Failed to fetch components from {ip}: {e}")
            finally:
                ssh_client.close()
                logger.info(f"SSH connection closed for server {ip}.")

    def close(self):
        try:
            self.db_connection.close()
            logger.info("Database connection closed.")
        except Exception as e:
            logger.error(f"Failed to close database connection: {e}")

if __name__ == "__main__":
    config_path = './config/config.yaml'  # Path to your JSON configuration file
    
    fetcher = ComponentFetcher(config_path)
    fetcher.fetch_and_store_components()
    fetcher.close()
