import json
import sys


if __name__=="__main__":
    manifest,node,text=json.load(sys.stdin)
    print(json.dumps(manifest["states"][node].get(text)))

