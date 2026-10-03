"""Rendered connector acceptance gate (optional Playwright/lxml tooling).

Uses the original hero measurement's WebKit getBBox/CTM and <=1-unit path
sampling. Checks *all* text, including nested/rotated text and section labels.
Decorative paths (icons, logo marks, accents, separators, schematic plots) are
inventoried but are not directed flow edges; generated edges use id=wN.
No nearest-card assignment can pass: each edge must declare data-target and
that named editable node must contain its endpoint strictly inside its outline.
Run with --assets DIR --output JSON; exit 1 means acceptance violations.
"""
import argparse
import itertools
import json
from pathlib import Path
from lxml import etree
from playwright.sync_api import sync_playwright

NAMES = ('decision-pipeline', 'information-flow', 'architecture', 'harnesses',
         'debate-flow', 'product-architecture')
JS = r'''() => {
const svg=document.querySelector('svg');
svg.pauseAnimations();svg.setCurrentTime(0);
const matrix=e=>svg.getScreenCTM().inverse().multiply(e.getScreenCTM());
const box=e=>{const b=e.getBBox(),m=matrix(e),p=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));return {x:Math.min(...p.map(q=>q.x)),y:Math.min(...p.map(q=>q.y)),w:Math.max(...p.map(q=>q.x))-Math.min(...p.map(q=>q.x)),h:Math.max(...p.map(q=>q.y))-Math.min(...p.map(q=>q.y))};};
const record=e=>({id:e.id,line:+e.dataset.line,cls:e.getAttribute('class'),label:e.textContent,box:box(e)});
const texts=[...svg.querySelectorAll('text')].filter(e=>!e.closest('defs')).map(record);
const nodes=[...svg.querySelectorAll('[data-node]')].map(record);
const edges=[...svg.querySelectorAll('path[id^="w"],line[data-target]')].map(e=>{
 const length=e.getTotalLength(),m=matrix(e),points=[];
 for(let i=0;i<=Math.ceil(length);i++){const q=e.getPointAtLength(length*i/Math.max(1,Math.ceil(length))).matrixTransform(m);points.push({x:q.x,y:q.y});}
 // Include the actual V marker geometry, transformed by the endpoint tangent.
 if(e.hasAttribute('marker-end')&&points.length>1){const end=points.at(-1),prev=points.at(-2),angle=Math.atan2(end.y-prev.y,end.x-prev.x),c=Math.cos(angle),s=Math.sin(angle),marker=svg.querySelector('marker path'),ml=marker.getTotalLength();
 for(let i=0;i<=Math.ceil(ml);i++){const q=marker.getPointAtLength(ml*i/Math.max(1,Math.ceil(ml))),x=q.x-6,y=q.y-5;points.push({x:end.x+x*c-y*s,y:end.y+x*s+y*c});}}
 const radius=+e.getAttribute('stroke-width')/2||.75;
 const nearest=texts.map(t=>{let best=Infinity,point=null;for(const q of points){const b=t.box,dx=Math.max(b.x-q.x,0,q.x-b.x-b.w),dy=Math.max(b.y-q.y,0,q.y-b.y-b.h),dist=Math.hypot(dx,dy);if(dist<best){best=dist;point=q;}}return {...t,distance:best,point};});
 const hits=nearest.filter(t=>t.distance<=radius);
 const hasPulse=[...svg.querySelectorAll('circle.pulse mpath')].some(p=>p.getAttribute('href')==='#'+e.id);
 const haloHits=hasPulse?nearest.filter(t=>t.distance<7):[];
 const target=nodes.find(n=>n.id===e.dataset.target),last=e.getPointAtLength(length).matrixTransform(m),end={x:last.x,y:last.y};
 let inside=false;
 if(target){const b=target.box;inside=end.x>b.x&&end.x<b.x+b.w&&end.y>b.y&&end.y<b.y+b.h;
 const el=svg.querySelector('#'+CSS.escape(target.id));
 if(el.tagName==='rect'&&el.isPointInFill){const pt=new DOMPoint(end.x,end.y).matrixTransform(matrix(el).inverse());inside=inside&&el.isPointInFill(pt);}}
 return {id:e.id,line:+e.dataset.line,source:e.dataset.source||null,target:e.dataset.target||null,end,targetBox:target?.box||null,endpointValid:inside,minimumTextDistance:Math.min(...nearest.map(t=>t.distance)),closestText:nearest.reduce((a,b)=>a.distance<b.distance?a:b),intersections:hits,haloIntersections:haloHits};
});
const rects=[...svg.querySelectorAll('svg > rect')].filter(e=>e.ownerSVGElement===svg&&!e.classList.contains('sweep')&&+e.getAttribute('width')>=60&&+e.getAttribute('height')>=30).slice(1).map(record);
const primitivePaths=[...svg.querySelectorAll('path,line')].filter(e=>!e.closest('defs')).map(e=>({line:+e.dataset.line,id:e.id,category:e.id.startsWith('w')?'connection':e.closest('.hero-icon')?'icon':e.ownerSVGElement!==svg?'logo':'accent/separator/schematic'}));
const artwork=[...svg.querySelectorAll('text,rect,path,line,g.hero-icon')].filter(e=>!e.closest('defs')).map(record);
const vb=svg.viewBox.baseVal;
const outside=artwork.filter(e=>e.box.x<-.01||e.box.y<-.01||e.box.x+e.box.w>vb.width+.01||e.box.y+e.box.h>vb.height+.01);
const overlap=(a,b)=>Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>.15&&Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>.15;
const textOverlaps=[];for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++)if(overlap(texts[i].box,texts[j].box))textOverlaps.push([texts[i],texts[j]]);
const iconOverlaps=[...svg.querySelectorAll('g.hero-icon')].flatMap(e=>texts.filter(t=>overlap(box(e),t.box)).map(t=>({icon:record(e),text:t})));
// Audit every non-edge path/line as well; graph membership is kept distinct from decorations.
const decorationHits=[];
for(const e of svg.querySelectorAll('path,line')){
 if(e.closest('defs')||e.id.startsWith('w'))continue;
 const len=e.getTotalLength(),m=matrix(e),r=(+e.getAttribute('stroke-width')||1)/2;
 const points=[];for(let i=0;i<=Math.ceil(len);i++){const q=e.getPointAtLength(len*i/Math.max(1,Math.ceil(len))).matrixTransform(m);points.push({x:q.x,y:q.y});}
 for(const t of texts){const b=t.box,hit=points.find(q=>q.x>=b.x-r&&q.x<=b.x+b.w+r&&q.y>=b.y-r&&q.y<=b.y+b.h+r);
 if(hit)decorationHits.push({pathLine:+e.dataset.line,text:t,point:hit});}
}
return {viewBox:svg.getAttribute('viewBox'),texts,nodes,rects,edges,primitivePaths,outside,textOverlaps,iconOverlaps,decorationHits};
}'''

def contains(a,b):
    return a['x']<=b['x'] and a['y']<=b['y'] and a['x']+a['w']>=b['x']+b['w'] and a['y']+a['h']>=b['y']+b['h']

def run(assets, executable=None, font=None, width=343, legacy=None):
    results={}
    with sync_playwright() as p:
        kwargs={'executable_path':executable} if executable else {}
        browser=p.webkit.launch(**kwargs)
        page=browser.new_page(viewport={'width':max(375,width+32),'height':812},device_scale_factor=2,reduced_motion='reduce')
        for name in NAMES:
            file=assets/(name+'.svg');root=etree.parse(str(file)).getroot()
            for el in root.iter():
                if isinstance(el.tag,str):el.set('data-line',str(el.sourceline))
            ambiguous=0
            if legacy:
                # Human-reviewed intended targets on the immutable old SVG.
                # Use line identities, never nearest-to-endpoint guesses.
                by_line={}
                for el in root.iter():
                    if isinstance(el.tag,str):by_line.setdefault(el.sourceline,el)
                by_id={el.get('id'):el for el in root.iter() if isinstance(el.tag,str)}
                for edge,lines in legacy[name].items():
                    for line in lines:
                        node=by_line[line]
                        node.set('id',f'legacy-node-{line}')
                        node.set('data-node','legacy-intended-target')
                    if len(lines)>1:
                        # A non-arrow trunk can already have explicit outgoing
                        # branches: its absent junction is an endpoint defect,
                        # not an additional undivided-arrow fanout defect.
                        if 'marker-end' in by_id[edge].attrib:
                            ambiguous+=1
                            by_id[edge].set('data-target','ambiguous-undivided-fanout')
                        else:by_id[edge].set('data-target','unowned-junction')
                    else:by_id[edge].set('data-target',f'legacy-node-{lines[0]}')
            page.set_content('<style>body{margin:16px}svg{width:343px;height:auto}</style>'+etree.tostring(root).decode())
            if font:page.add_style_tag(content=f'svg text:not(.code){{font-family:{font}!important}}')
            if width!=343:page.add_style_tag(content=f'svg{{width:{width}px}}')
            page.evaluate('document.fonts.ready')
            data=page.evaluate(JS)
            gaps=[]
            for a,b in itertools.combinations(data['rects'],2):
                aa,bb=a['box'],b['box']
                if contains(aa,bb) or contains(bb,aa):continue
                dx=max(aa['x'],bb['x'])-min(aa['x']+aa['w'],bb['x']+bb['w'])
                dy=max(aa['y'],bb['y'])-min(aa['y']+aa['h'],bb['y']+bb['h'])
                if dx<0:gaps.append({'gap':dy,'axis':'y','lines':[a['line'],b['line']]})
                elif dy<0:gaps.append({'gap':dx,'axis':'x','lines':[a['line'],b['line']]})
            distribution={}
            for cls in sorted({t['cls'] for t in data['texts'] if t['cls']}):
                ys=sorted({round(t['box']['y'],2) for t in data['texts'] if t['cls']==cls})
                distances=[round(b-a,2) for a,b in zip(ys,ys[1:])]
                distribution[cls]={str(d):distances.count(d) for d in sorted(set(distances))}
            hits=sum(len(e['intersections']) for e in data['edges'])
            endpoints=sum(not e['endpointValid'] for e in data['edges'])
            node_ids={n['id'] for n in data['nodes']}
            undeclared=sum(e['source'] not in node_ids or not e['target'] for e in data['edges'])
            groups={}
            for e in data['edges']:
                if e['source']:groups.setdefault(e['source'],[]).append(e['target'])
            fanouts={k:v for k,v in groups.items() if len(v)>1}
            fanout_errors=ambiguous+sum(not all(v) or len(set(v))!=len(v) for v in fanouts.values())
            halos=sum(len(e['haloIntersections']) for e in data['edges'])
            data.update(fanOutTargets=fanouts,fanOutErrorCount=fanout_errors,haloIntersectionCount=halos,intersectionCount=hits,invalidEndpointCount=endpoints,undeclaredEdgeCount=undeclared,
                        minimumGap=min((g['gap'] for g in gaps),default=None),gaps=sorted(gaps,key=lambda g:g['gap'])[:12],
                        yIntervalDistribution=distribution,renderWidth=width,viewportWidth=max(375,width+32),fontOverride=font)
            results[name]=data
            print(f'{name}: text-intersections={hits} invalid-endpoints={endpoints} undeclared-edges={undeclared} fanout-errors={fanout_errors} halo-intersections={halos} min-gap={data["minimumGap"]:.2f} outside={len(data["outside"])} text-overlaps={len(data["textOverlaps"])} icon-overlaps={len(data["iconOverlaps"])} decorative-path-hits={len(data["decorationHits"])}')
            for edge in data['edges']:
                if not edge['endpointValid']:
                    print(f"  END {name}.svg:{edge['line']} #{edge['id']} -> {edge['target']} end={edge['end']} target-box={edge['targetBox']}")
                for key in ('intersections','haloIntersections'):
                    for text in edge[key]:
                        print(f"  TEXT {name}.svg:{edge['line']} #{edge['id']} {key} text:{text['line']} {text['label']} point={text['point']} bbox={text['box']}")
        browser.close()
    return results

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--assets',type=Path,default=Path(__file__).resolve().parents[1]/'assets')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--webkit-executable')
    ap.add_argument('--font',choices=('Arial','Inter'))
    ap.add_argument('--width',type=int,default=343)
    ap.add_argument('--legacy-targets',type=Path,help='Reviewed target element lines for the old baseline only')
    args=ap.parse_args();data=run(args.assets,args.webkit_executable,args.font,args.width,json.loads(args.legacy_targets.read_text()) if args.legacy_targets else None)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    n=sum(d['intersectionCount']+d['invalidEndpointCount']+d['fanOutErrorCount']+d['haloIntersectionCount']+len(d['decorationHits'])+len(d['outside'])+len(d['textOverlaps'])+len(d['iconOverlaps']) for d in data.values())
    print(f'TOTAL: {n} acceptance violations')
    return int(n>0 or any(d['undeclaredEdgeCount'] for d in data.values()))

if __name__=='__main__':
    raise SystemExit(main())
