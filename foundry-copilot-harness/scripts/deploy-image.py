import argparse

from cloud import update_app, wait_status

parser = argparse.ArgumentParser(description="Update only the harness demo image, preserving runtime configuration")
parser.add_argument("image", help="Reviewed image digest in the existing registry")
args = parser.parse_args()
origin = update_app(image=args.image)
wait_status(origin, "/healthz", 200)
print(f"Image updated and health verified: {origin}")
