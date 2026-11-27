"""Register the two scenario evidence operations under the existing authenticated API."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy as arm
from dart_routes import API, VERSION

OPERATIONS = [
    ("scenario-analyze-with-evidence", "/stress/scenario/analyze", []),
    ("scenario-news-scenarios", "/stress/analyses/{analysis_id}/news-scenarios",
     [{"name":"analysis_id","required":True,"type":"string"}]),
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    current=arm.call(API+"/operations",VERSION).get("value",[])
    for name,path,params in OPERATIONS:
        found=next((x for x in current if x["name"]==name),None)
        expected=dict(method="POST",urlTemplate=path)
        if found and any(found["properties"].get(k)!=v for k,v in expected.items()):
            raise RuntimeError("Operation ID already has another purpose")
        if args.apply and not found:
            arm.call(API+"/operations/"+name,VERSION,"PUT",
                     {"properties":dict(expected,displayName=name,templateParameters=params,responses=[])})
        print(name, "present" if found else "created" if args.apply else "planned")


if __name__=="__main__":
    main()
