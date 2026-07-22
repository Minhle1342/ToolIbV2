import requests

url = "http://127.0.0.1:5000/api/upload-folder"
files = [
    ('files', ('dataset_tags.json', open('exported_dataset/dataset_tags.json', 'rb'), 'application/json'))
]
data = {'project_name': 'test_upload_json'}

try:
    r = requests.post(url, files=files, data=data)
    print(r.json())
except Exception as e:
    print(e)
