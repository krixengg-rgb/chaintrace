t(){ J=$(curl -s -X POST "localhost:8090/api/trace?q=$1&hops=$2&direction=$3&topk=${4:-3}" | python3 -c "import json,sys;print(json.load(sys.stdin)['job'])")
 for i in $(seq 1 300); do S=$(curl -s localhost:8090/api/trace/$J); st=$(echo "$S"|python3 -c "import json,sys;print(json.load(sys.stdin)['status'])"); [ "$st" = running ] || [ "$st" = queued ] || break; sleep 2; done
 echo "$S" | python3 -c "
import json,sys,collections;j=json.load(sys.stdin)
print('##',j['chain'],j['q'][:14],j['direction'],j['hops'],j['status'],j.get('elapsed'),'s nodes',len(j['nodes']),'labelled',dict(collections.Counter(n.get('kind') for n in j['nodes'] if n.get('kind') and n['kind']!='tx')))
print('   risk',j.get('risk',{}).get('score'),j.get('risk',{}).get('level'))
[print('   path',p['kind'],p['hops'],'|',p.get('name'),'|',p.get('sources')) for p in j['paths'][:6]]"; }
