import os
import json
import argparse
import sys
import re

class ComponentDetector:
    def __init__(self, base_dir, max_depth=3):
        self.base_dir = base_dir
        self.max_depth = max_depth
        self.exclude_keywords = ['script', 'watcher', 'tar', 'runtime', 'backup', 'jdk', 'dd-agent']
        self.special_keywords = {'solr': 'Java', 'opa': 'opa'}
        self.file_extensions = {'.jar': 'Java'}
        self.so_pattern = re.compile(r"\.so(\.\d+)*$") # Matches .so and .so.version
        self.status = "failure"
        self.components = []
        self.message = ''

    def is_excluded_directory(self, dir_name):
        return any(keyword in dir_name.lower() for keyword in self.exclude_keywords)

    def get_platform(self, dir_name):
        for keyword, platform in self.special_keywords.items():
            if keyword in dir_name.lower():
                return platform
        return None

    def identify_component(self, dir_path):
        comp_name = os.path.basename(dir_path)
        platform = self.get_platform(comp_name)

        if os.path.isdir(dir_path) and platform:
            return {"comp_name": comp_name, "platform": platform, "path": dir_path}

        try:
            files = os.listdir(dir_path)
        except (OSError, IOError) as e:
            raise e

        for file in files:
            for extension, platform in self.file_extensions.items():
                if file.endswith(extension):
                    return {"comp_name": comp_name, "platform": platform, "path": dir_path}
            if self.so_pattern.search(file):
                return {"comp_name": comp_name, "platform": "C++", "path": dir_path}

        for sub_dir in ['bin', 'lib']:
            sub_dir_path = os.path.join(dir_path, sub_dir)
            if os.path.isdir(sub_dir_path):
                try:
                    files = os.listdir(sub_dir_path)
                except (OSError, IOError):
                    continue

                for file in files:
                    for extension, platform in self.file_extensions.items():
                        if file.endswith(extension):
                            return {"comp_name": comp_name, "platform": platform, "path": dir_path}
                    if self.so_pattern.search(file):
                        return {"comp_name": comp_name, "platform": "C++", "path": dir_path}

        return None

    def get_valid_directories(self, current_dir):
        dirs = []
        try:
            for directory in os.listdir(current_dir):
                dir_path = os.path.join(current_dir, directory)
                if os.path.isdir(dir_path) and not self.is_excluded_directory(directory):
                    dirs.append(dir_path)
        except OSError:
            self.status = "failure"
            self.message = "{} not found".format(current_dir)
        except IOError:
            self.status = "failure"
            self.message = "Permission denied for accessing {}".format(current_dir)
        return dirs

    def traverse_directory(self, dir_path, depth):
        if depth > self.max_depth:
            return
        dirs = self.get_valid_directories(dir_path)
        for subdir_path in dirs:
            component = self.identify_component(subdir_path)
            if component:
                self.components.append(component)
            else:
                self.traverse_directory(subdir_path, depth + 1)

    def gather_components(self):
        self.traverse_directory(self.base_dir, 1)
        self.status = "success"

    def run(self):
        try:
            self.gather_components()
            response = {
                "status": self.status,
                "components": self.components,
                "message": self.message
            }
            print(json.dumps(response))
        except Exception as e:
            response = {
                "status": "failure",
                "components": self.components,
                "message": str(e)
            }
            print(json.dumps(response))

if __name__ == "__main__":
    # Ensure compatibility with Python 2 and 3 for input function
    if sys.version_info[0] < 3:
        input = raw_input

    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Gather components from a directory.")
    parser.add_argument('base_dir', type=str, help='Base directory to start the search')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Create an instance of ComponentDetector and run
    detector = ComponentDetector(args.base_dir)
    detector.run()
