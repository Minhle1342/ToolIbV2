import os
import shutil
from app import create_app
from models import db, Project, View, Image
import utils

# Setup dummy data
TEST_DIR = os.path.abspath("test_data")
IMAGES_DIR = os.path.join(TEST_DIR, "images")
CLASSES_FILE = os.path.join(IMAGES_DIR, "classes.txt")

if os.path.exists(TEST_DIR):
    shutil.rmtree(TEST_DIR)
os.makedirs(IMAGES_DIR)

# Create dummy images
for i in range(1, 6):
    with open(os.path.join(IMAGES_DIR, f"img_{i}.jpg"), 'w') as f:
        f.write("dummy content")

# Create dummy classes
with open(CLASSES_FILE, 'w') as f:
    f.write("cat\ndog\ncar")

app = create_app()

with app.app_context():
    # 1. Reset DB
    db.drop_all()
    db.create_all()
    print("DB Initialized.")

    # 2. Create Project
    p = Project(name="Test Project", root_path=IMAGES_DIR)
    db.session.add(p)
    db.session.commit()
    print(f"Project Created: {p.id}")

    # 3. Test Scan
    added = utils.scan_and_sync_images(p)
    print(f"Scanned {added} images.")
    assert added == 5, "Should have found 5 images"

    # 4. Test View & Assign
    v = View(name="Test View", project_id=p.id)
    db.session.add(v)
    db.session.commit()
    
    assigned = utils.assign_images_to_view(v.id, 2, p.id)
    print(f"Assigned {assigned} images.")
    assert assigned == 2, "Should have assigned 2 images"
    
    # Verify assignment
    img = Image.query.filter_by(view_id=v.id).first()
    print(f"Image {img.filename} assigned to View {img.view_id}")

    # 5. Test Label Save
    img_to_label = Image.query.filter_by(filename="img_1.jpg").first()
    dummy_label = [{'class_id': 0, 'x': 0.5, 'y': 0.5, 'w': 0.1, 'h': 0.1}]
    utils.save_yolo_label(img_to_label, dummy_label)
    img_to_label.is_labeled = True
    db.session.commit()
    print("Label saved.")
    
    # Reload and Check
    loaded_labels = utils.read_yolo_label(img_to_label)
    print(f"Loaded labels: {loaded_labels}")
    assert len(loaded_labels) == 1
    assert loaded_labels[0]['class_id'] == 0

    # 6. Test Export
    print("Testing Export...")
    res = utils.export_dataset({'project_ids': [p.id]}, 0.8)
    print("Export Result:", res)
    assert res['status'] == 'success'
    assert os.path.exists(res['export_path'])
    assert os.path.exists(os.path.join(res['export_path'], 'data.yaml'))
    assert res['stats']['total'] == 1 # We labeled 1 image
    
    # Verify label exists in same folder as image
    label_path = os.path.join(p.root_path, "img_1.txt")
    assert os.path.exists(label_path), "Label should exist in the same folder"

    print("Backend Logic (including Export) Verified Successfully!")
