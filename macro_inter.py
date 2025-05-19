class MacroInterpreter:
    def __init__(self):
        self.variables = {}
        self.statements = []
        self.position = 0

    def parse(self, lines):
        stack = []
        self.statements = []
        current_block = self.statements

        for lineno, line in enumerate(lines, start=1):
            line = line.strip()
            if not line or line.startswith('//'):
                continue  # Ignore empty lines and comments

            # For each meaningful statement, record the original line number.
            if line.startswith('var '):
                var_name = line[4:].strip()
                self.variables[var_name] = None
                continue
            elif line.startswith('CV'):
                cv_options = line[3:].strip()
                tab_cv_options = cv_options.split(',')
                Ei = float(tab_cv_options[0])
                E1 = float(tab_cv_options[1])
                E2 = float(tab_cv_options[2])
                Ef = float(tab_cv_options[3])
                cv_scan_rate = float(tab_cv_options[4])
                cv_n_cycle = int(tab_cv_options[5])
                current_block.append({
                    'type': 'CV',
                    'Ei': Ei,
                    'E1': E1,
                    'E2': E2,
                    'Ef': Ef,
                    'scan_rate': cv_scan_rate,
                    'n_cycle': cv_n_cycle,
                    'line_number': lineno
                })
            elif line.startswith('CV_FILE'):
                cv_file_name = line[8:].strip('()')
                current_block.append({
                    'type': 'CV_FILE',
                    'name': cv_file_name,
                    'line_number': lineno
                })
            elif line.startswith('LOOP'):
                loop_count = int(line[5:].strip(' ()'))
                loop_statement = {
                    'type': 'LOOP',
                    'count': loop_count,
                    'body': [],
                    'line_number': lineno
                }
                current_block.append(loop_statement)
                stack.append(current_block)
                current_block = loop_statement['body']
            elif line == 'END_LOOP':
                current_block = stack.pop()
            elif line.startswith('IF'):
                condition = line[3:].strip(' ()')
                if_statement = {
                    'type': 'IF',
                    'condition': condition,
                    'body': [],
                    'line_number': lineno
                }
                current_block.append(if_statement)
                stack.append(current_block)
                current_block = if_statement['body']
            elif line == 'END_IF':
                current_block = stack.pop()
            elif line == 'STOP':
                current_block.append({'type': 'STOP', 'line_number': lineno})
                return  # Stop parsing further lines
            else:
                # Regular command
                current_block.append({
                    'type': 'COMMAND',
                    'line': line,
                    'line_number': lineno
                })

    def execute(self, highlight_callback=None):
        self.execute_block(self.statements, highlight_callback)

    def execute_block(self, statements, highlight_callback=None):
        for statement in statements:
            # Call the highlight callback if provided.
            if highlight_callback and 'line_number' in statement:
                highlight_callback(statement['line_number'])
            if statement['type'] == 'COMMAND':
                self.execute_command(statement['line'])
            elif statement['type'] == 'LOOP':
                for _ in range(statement['count']):
                    self.execute_block(statement['body'], highlight_callback)
            elif statement['type'] == 'IF':
                condition = statement['condition']
                if self.evaluate_condition(condition):
                    self.execute_block(statement['body'], highlight_callback)
            elif statement['type'] == 'STOP':
                return  # Stop execution

    # (The rest of the class remains unchanged)
            
    
    def execute_command(self, line):
        if line.startswith('MOVE'):
            params = self.parse_parameters(line)
            x, y, z = params
            self.move(x, y, z)

        elif line.startswith('SET_VOLTAGE'):
            params = self.parse_parameters(line)
            voltage = params[0]
            self.set_voltage(voltage)

        elif line.startswith('READ_CURRENT'):
            parts = line.split()
            if len(parts) == 2:
                var_name = parts[1]
                current = self.read_current()
                self.variables[var_name] = current
            else:
                current = self.read_current()
                print(current)

        elif line.startswith('PRINT'):
            params = self.parse_parameters(line)
            for param in params:
                if isinstance(param, str) and param in self.variables:
                    print(self.variables[param])
                else:
                    print(param)

        elif line.startswith('PAUSE'):
            params = self.parse_parameters(line)
            time = params[0]
            self.pause(time)

        else:
            print(f"Unknown command: {line}")
        

    def parse_parameters(self, line):
        import re
        # Extract text inside parentheses
        m = re.search(r'\((.*)\)', line)
        if m:
            params_str = m.group(1)
            # Split parameters by comma
            params = [param.strip() for param in params_str.split(',')]
            # Convert parameters to appropriate types
            converted_params = []
            for param in params:
                if param in self.variables and self.variables[param] is not None:
                    converted_params.append(self.variables[param])
                else:
                    try:
                        converted_params.append(float(param))
                    except ValueError:
                        converted_params.append(param.strip('"'))
            return converted_params
        else:
            return []
        
    
    def evaluate_condition(self, condition):
        # Replace variable names with their values
        for var in self.variables:
            if var in condition:
                value = self.variables[var]
                condition = condition.replace(var, str(value))
        # Evaluate the condition
        try:
            return eval(condition)
        except Exception as e:
            print(f"Error evaluating condition '{condition}': {e}")
            return False
        
    
    def move(self, x, y, z):
        print(f"Moving to position ({x}, {y}, {z})")

    def set_voltage(self, voltage):
        print(f"Setting voltage to {voltage}")

    def read_current(self):
        # Simulate reading current
        import random
        current = random.uniform(0, 20)
        print(f"Reading current: {current}")
        return current

    def pause(self, time_duration):
        print(f"Pausing for {time_duration} seconds")
        import time as time_module
        time_module.sleep(time_duration)



def main():
    with open('macro_file.txt', 'r') as f:
        lines = f.readlines()
    interpreter = MacroInterpreter()
    interpreter.parse(lines)
    interpreter.execute()

if __name__ == '__main__':
    main()
