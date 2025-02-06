import mysql.connector
from prettytable import PrettyTable

class RemoteDatabaseSearcher:
    def __init__(self, db_config):
        self.db_config = db_config
        self.connection = None
        self.cursor = None

    def connect(self):
        # Establish the MySQL database connection
        self.connection = mysql.connector.connect(**self.db_config)
        self.cursor = self.connection.cursor()

    def search_by_name_or_ip(self, partial_value):
        # Prepare and execute the SQL query to search for components by component name or IP address
        query = """
        SELECT region, ip, component_name, platform, comp_path 
        FROM components 
        WHERE component_name LIKE %s OR ip LIKE %s 
        ORDER BY region, ip, component_name
        """
        self.cursor.execute(query, (f"%{partial_value}%", f"%{partial_value}%"))
        results = self.cursor.fetchall()

        # Process and display results
        if results:
            table = PrettyTable()
            table.field_names = ["Region", "IP Address", "Component Name", "Platform", "Path"]
            table.align["Region"] = "l"
            table.align["IP Address"] = "l"
            table.align["Component Name"] = "l"
            table.align["Platform"] = "l"
            table.align["Path"] = "l"
            
            for row in results:
                table.add_row(row)

            print(table)
        else:
            print(f"No components or IPs found with '{partial_value}'.")

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()

if __name__ == "__main__":
    # Define your MySQL database details
    db_config = {
        'user': 'directfn',
        'password': 'mubasher',
        'host': '172.20.162.55',
        'database': 'COMPONENT_DB'
    }

    searcher = RemoteDatabaseSearcher(db_config)
    searcher.connect()
    
    while True:
        value_part = input("Enter part of the component name or IP to search (or type 'exit' to quit): ")
        if value_part.lower() == 'exit':
            print("Exiting the search loop.")
            break
        searcher.search_by_name_or_ip(value_part)
    
    searcher.close()
