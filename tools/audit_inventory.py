"""Static control/module inventory, explicitly not an end-to-end test claim."""
import ast,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WIDGETS={'CTkButton','CTkSwitch','CTkCheckBox','CTkOptionMenu','OptionMenu','CTkEntry','CTkSlider','CTkProgressBar','button','ghost_button','_switch_row','_check'}

def inventory():
    modules=[];controls=[];sensitive=[]
    for path in sorted(ROOT.rglob('*.py')):
        relative=path.relative_to(ROOT)
        if any(part.startswith('.') or part in ('dist','build','tests','__pycache__') for part in relative.parts):continue
        if relative.parts[:2]==('tools','fixtures'):continue
        source=path.read_text(encoding='utf-8-sig');tree=ast.parse(source)
        modules.append(str(relative).replace('\\','/'))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            name=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
            if name in WIDGETS:
                kw={value.arg:ast.unparse(value.value) for value in node.keywords if value.arg}
                controls.append(dict(module=str(relative),line=node.lineno,type=name,command=kw.get('command'),variable=kw.get('variable') or kw.get('textvariable'),caption=kw.get('text'),verification='STATIC INVENTORY ONLY'))
            if name in ('Popen','run','startfile','extractall','open_url','verify_manifest','verify_file'):
                sensitive.append(dict(module=str(relative),line=node.lineno,call=ast.unparse(node.func)))
    return dict(scope='Static source inventory; callbacks defined later or through wrappers require manual tracing; no runtime PASS implied',modules=modules,controls=controls,security_sensitive_calls=sensitive)

if __name__=='__main__':
    target=ROOT/'dist'/'Veyora-Pro-2.0.3-Control-Inventory.json';target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(inventory(),ensure_ascii=False,indent=2),encoding='utf8')
    print('Static inventory saved')
