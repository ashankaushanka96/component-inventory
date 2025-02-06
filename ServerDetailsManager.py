import os
import boto3
import paramiko
import mysql.connector
import yaml
import datetime
from loguru import logger

class ServerDetailsManager:
    def __init__(self, config_file, script_directory):
                # Load configuration from YAML file
        with open(config_file, 'r') as file:
            self.config = yaml.safe_load(file)

        # AWS Regions and Datacenter configurations
        self.regions = self.config['aws']['regions']
        self.datacenters = self.config['datacenters']
        
        # Database connection setup
        self.db_config = self.config['db_config']
        self.db_connection = mysql.connector.connect(**self.db_config)
        self.cursor = self.db_connection.cursor()

        # Set up logging
        log_file_path = os.path.join(script_directory, './logs/server_details_manager_{time:YYYYMMDDHHmmss}.log')
        logger.add(
            log_file_path,
            rotation="1 day",  # Rotate log files daily
            retention="2 days",  # Retain log files for 2 days
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {message}"
        )

    def get_all_servers(self):
        servers = []

        # Fetch AWS servers only if regions are defined
        if self.regions:
            for region, region_data in self.regions.items():
                ec2 = boto3.resource('ec2', region_name=region)
                instances = ec2.instances.all()  # Get all instances
                for instance in instances:
                    team_tag = next((tag['Value'] for tag in instance.tags if tag['Key'] == 'Team'), None)
                    if team_tag is None or team_tag.lower() != "tradeops":
                        server_name = next((tag['Value'] for tag in instance.tags if tag['Key'] == 'Name'), None)
                        servers.append({
                            'ip': instance.private_ip_address,
                            'region': region,
                            'key_path': region_data["key_path"],
                            'running_state': instance.state['Name'],
                            'server_name': server_name,
                        })
        
        # Fetch TCN and LDC servers from config
        if self.datacenters:
            for datacenter, datacenter_data in self.config["datacenters"].items():
                for ip in datacenter_data["ips"]:
                    servers.append({
                        'ip': ip,
                        'region': datacenter,
                        'key_path': datacenter_data["key_path"],
                        'user': datacenter_data["user"],
                        'running_state': "running",  # Set as running by default
                        'server_name': None,
                    })
        
        return servers


    def check_os_type(self, ssh_client):
        try:
            stdin, stdout, stderr = ssh_client.exec_command("cat /etc/os-release")
            os_info = stdout.read().decode('utf-8')
            if "Amazon Linux" in os_info:
                return "amazon-linux"
            elif "CentOS" in os_info:
                return "centos"
            return None
        except Exception as e:
            logger.error(f"Error while checking OS type: {e}")
            return None

    def attempt_connection(self, ip, user, key_path):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            ssh_client.connect(hostname=ip, username=user, key_filename=key_path, timeout=10)
            logger.info(f"Successfully connected to {ip} as {user}.")
            return ssh_client
        except Exception as e:
            logger.warning(f"Connection with {user} failed on {ip}: {e}")
            return None

    def get_user_from_db(self, ip):
        try:
            self.cursor.execute("SELECT user FROM servers WHERE server_ip = %s", (ip,))
            result = self.cursor.fetchone()
            return result[0] if result else None
        except mysql.connector.Error as e:
            logger.error(f"Error while retrieving user from DB for IP {ip}: {e}")
            return None

    def server_exists_in_db(self, ip):
        try:
            self.cursor.execute("SELECT 1 FROM servers WHERE server_ip = %s and update_status = %s", (ip,'Success',))
            exists = self.cursor.fetchone() is not None
            return exists
        except mysql.connector.Error as e:
            logger.error(f"Error while checking if server exists in DB for IP {ip}: {e}")
            return False

    def update_servers_table(self):

        servers = self.get_all_servers()  # Get all servers, both running and not running

        # Sort servers by IP address
        servers.sort(key=lambda server: server['ip'])

        for server in servers:
            ip = server['ip']
            region = server['region']
            key_path = server['key_path']
            running_state = server['running_state']
            server_name = server['server_name']

            # Default values for update status and error message
            update_status = 'Success'
            error_message = None

            # Get the current timestamp for last update time
            last_updated_time = datetime.datetime.now()

            # Skip if server already exists in the database
            if self.server_exists_in_db(ip):
                logger.info(f"Skipping server {ip} as it already exists in the database.")
                continue  # Skip to the next server
            
            os_type = None
            search_path = None

            # For stopped servers, no need to check OS type or attempt connection
            if running_state == 'running':
                # Check if user is already in the database
                user = self.get_user_from_db(ip)

                if user is None:
                    # If user is not in the database, default to ec2-user or centos
                    user = server.get('user', 'ec2-user')  # Default to 'ec2-user' for AWS instances
                ssh_client = self.attempt_connection(ip, user, key_path)
                if ssh_client is None:
                    user = 'centos'  # Second try
                    ssh_client = self.attempt_connection(ip, user, key_path)
                    if ssh_client is None:
                        user = 'rocky'  # Third try
                        ssh_client = self.attempt_connection(ip, user, key_path)
                if ssh_client:
                    try:
                        os_type = self.check_os_type(ssh_client)
                        logger.info(f"Connected to {ip} with {user}. OS: {os_type}")

                        # Check if /apps directory exists
                        stdin, stdout, stderr = ssh_client.exec_command("test -d /apps && echo 'exists' || echo 'not exists'")
                        search_path = "/apps" if stdout.read().decode().strip() == 'exists' else "/home/directfn/app"
                        logger.info(f"Using search path: {search_path}")

                    except Exception as e:
                        logger.error(f"Failed to execute commands on {ip}: {e}")
                        update_status = 'Failure'
                        error_message = f"Failed to execute commands on {ip}: {e}"
                        search_path = None  # Set search_path to None if command execution fails
                    finally:
                        ssh_client.close()
                else:
                    user = None
                    search_path = None  # No SSH connection if failed to connect
                    update_status = 'Failure'
                    error_message = f"Failed to connect to {ip} with users : [ec2-user, centos, rocky]"
            else:
                # If server is not running, we don't attempt to connect
                logger.info(f"Server {ip} is not running. Skipping OS type check and search path determination.")
                search_path = None
                update_status = 'Failure'
                error_message = f"Server {ip} is not running."

            # Insert or update server details into the servers table
            try:
                self.cursor.execute(
                    """
                    INSERT INTO servers (server_ip, os, user, search_path, region, running_state, server_name, last_updated_time, update_status, error_message) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                    ON DUPLICATE KEY UPDATE 
                        os=%s, user=%s, search_path=%s, region=%s, running_state=%s, server_name=%s, last_updated_time=%s, update_status=%s, error_message=%s
                    """,
                    (
                        ip, os_type, user, search_path, region, running_state, server_name, last_updated_time, update_status, error_message,
                        os_type, user, search_path, region, running_state, server_name, last_updated_time, update_status, error_message
                    )
                )
                self.db_connection.commit()
                logger.info(f"Server {ip} details updated successfully.")
            except mysql.connector.Error as e:
                logger.error(f"Error while inserting/updating server {ip}: {e}")
                self.db_connection.rollback()

    def close(self):
        try:
            self.db_connection.close()
            logger.info("Database connection closed.")
        except Exception as e:
            logger.error(f"Failed to close database connection: {e}")

if __name__ == "__main__":
    config_file = './config/config.yaml'
    script_directory = os.path.dirname(os.path.realpath(__file__))

    manager = ServerDetailsManager(config_file, script_directory)
    manager.update_servers_table()
    manager.close()
