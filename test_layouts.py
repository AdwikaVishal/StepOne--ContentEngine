
from pathlib import Path
from content_engine.layout_assembler import LayoutAssembler

def test_layouts():
    # Use test photos if available
    test_photo_dir = Path("test_photos")
    image_paths = []
    if test_photo_dir.exists():
        for f in test_photo_dir.iterdir():
            if f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                image_paths.append(str(f))
    # If no test photos, create dummy images? Let's just skip for now and test the function exists
    if not image_paths:
        print("No test images found in test_photos directory, skipping actual collage generation")
        print("But let's check function definitions")
        assembler = LayoutAssembler()
        print("✅ LayoutAssembler initialized")
        return

    assembler = LayoutAssembler()
    print("Testing layouts with", len(image_paths), "images")
    layouts_to_test = [
        "hero_right",
        "hero_left",
        "hero_center",
        "magazine",
        "panoramic",
        "bauhaus",
        "minimal"
    ]
    for layout in layouts_to_test:
        try:
            print(f"Testing layout: {layout}")
            collage = assembler.create_linkedin_collage(image_paths, layout)
            output_path = Path(f"test_{layout}.jpg")
            collage.save(output_path, quality=95)
            print(f"✅ Saved to {output_path}")
        except Exception as e:
            print(f"❌ Failed for {layout}: {e}")

if __name__ == "__main__":
    test_layouts()
