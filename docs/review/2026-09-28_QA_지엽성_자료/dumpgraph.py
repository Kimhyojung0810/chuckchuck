import json,sys
g=json.load(open(sys.argv[1]))
g=g.get('graph',g) if 'nodes' not in g else g
nodes=g['nodes']; edges=g['edges']
par={e['to']:e['from'] for e in edges if e['kind']=='parent'}
kids={}
for c,p in par.items(): kids.setdefault(p,[]).append(c)
print(g.get('file_name'), len(nodes),'nodes', len(edges),'edges', sum(e['kind']=='parent' for e in edges),'parent')
def dep(i):
    d=0
    while i in par: i=par[i]; d+=1
    return d
for n in sorted(nodes,key=lambda n:-n['weight']):
    print(f"{n['weight']:.3f} d{dep(n['id'])} kids{len(kids.get(n['id'],[]))} {n.get('importance','?'):7s} {n['label'][:22]:22s} S{n['slide_nos']} <- {par.get(n['id'],'')}")
print([ (s['name'],s['slide_role'],s['slide_nos']) for s in g.get('sections',[])])
