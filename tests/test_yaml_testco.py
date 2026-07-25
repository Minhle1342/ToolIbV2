import yaml

try:
    with open(r"D:\TestcoYaml\data.yaml", 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        print("Data loaded:", data)
        if data and 'names' in data:
            names = data['names']
            print("Names:", names)
            if isinstance(names, dict):
                def sort_key(k):
                    try:
                        return (0, int(k))
                    except (ValueError, TypeError):
                        return (1, str(k))
                names = [str(names[k]) for k in sorted(names.keys(), key=sort_key)]
            elif isinstance(names, list):
                names = [str(n) for n in names]
            print("Final names:", names)
except Exception as e:
    print(f"Error parsing data.yaml: {e}")
