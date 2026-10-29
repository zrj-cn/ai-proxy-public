"""CI-only: obtain pinned official core without installing services or application settings."""
import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy import core as c
c.init();target=c.download_version(c.read(c.ROOT/'versions.json')['default']);c.switch_binary(target)
print('Official pinned core SHA256 verified')
