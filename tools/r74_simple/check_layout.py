"""Acceptance: one visible Windows entry point and no nested archives."""
from pathlib import Path
import json, sys, zipfile


def inspect(path):
    with zipfile.ZipFile(path) as z:
        files=[n for n in z.namelist() if not n.endswith('/')]
        roots={n.split('/')[0] for n in files}
        if len(roots)!=1:
            return {'ok':False,'error':'Expected exactly one folder'}
        root=next(iter(roots)); relative=[n[len(root)+1:] for n in files]
        nested=[n for n in relative if Path(n).suffix.lower() in ('.zip','.whl','.gz','.7z','.rar','.tar')]
        commands=[n for n in relative if Path(n).suffix.lower() in ('.cmd','.bat','.ps1')]
        visible=sorted({n.split('/')[0] for n in relative})
        result=dict(no_nested_archives=not nested,one_start_command=commands==['START.cmd'],
                    one_system_directory=visible==['INSTRUCTION_RU.txt','START.cmd','system'],
                    nested_archives=nested,commands=commands,top_level=visible,crc_ok=z.testzip() is None)
        result['ok']=all(result[k] for k in ('no_nested_archives','one_start_command','one_system_directory','crc_ok'))
        return result

if __name__=='__main__':
    result=inspect(sys.argv[1]);print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['ok'] else 1)
