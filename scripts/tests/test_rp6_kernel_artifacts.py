"""Reject inconsistent packed kernel bundles before image assembly."""
import gzip
import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'scripts/check-rp6-kernel.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtput'), 'requires DT compiler')
class KernelArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name); self.bundle = self.folder / 'bundle'
        self.rel = '7.2.8-sm8550-steamos'
        self.mod = self.bundle / 'modules' / self.rel / 'kernel/test.ko'
        self.mod.parent.mkdir(parents=True)
        # ELF64 AArch64 relocatable module metadata (not executable code).
        self.mod.write_bytes(b'\x7fELF\x02\x01\x01' + b'\0'*9 + struct.pack('<HH', 1, 183) + b'\0'*44 +
                             b'\0vermagic=' + self.rel.encode() + b' SMP mod_unload aarch64\0')
        self.init = {name: (REPO / 'external-and-mods/kernel-common/initramfs' / name).read_bytes()
                     for name in ('init', 'mount-etc-overlay', 'konkr-update-recover', 'bootdebug')}
        self.init['bin/busybox'] = b'fixture busybox'
        self.firmware = {}
        self.lock = {'format': 'rp6-kernel-inputs-1', 'kernel': '7.2.8', 'recipe': '7.2', 'inputs': [],
                     'toolchain': {'busybox_sha256': hashlib.sha256(self.init['bin/busybox']).hexdigest()}}
        for name,path in [('gpu-sqe','qcom/a740_sqe.fw'),('gpu-gmu','qcom/gmu_gen70200.bin'),
                          ('gpu-zap','qcom/sm8550/a740_zap.mbn'),('wifi-amss','ath12k/WCN7850/hw2.0/amss.bin'),
                          ('wifi-m3','ath12k/WCN7850/hw2.0/m3.bin'),('wifi-board','ath12k/WCN7850/hw2.0/board-2.bin'),
                          ('regdb','regulatory.db'),('regdb-signature','regulatory.db.p7s')]:
            data=('fixture '+name).encode(); self.firmware[path]=data
            dest=self.bundle/'firmware'/path; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(data)
            self.lock['inputs'].append({'id':name,'sha256':hashlib.sha256(data).hexdigest()})
        self.lockfile=self.folder/'lock.json';self.lockfile.write_text(json.dumps(self.lock))
        self.config='CONFIG_OVERLAY_FS=y\nCONFIG_IKCONFIG=y\nCONFIG_IKCONFIG_PROC=y\nCONFIG_INITRAMFS_COMPRESSION_NONE=y\nCONFIG_EXTRA_FIRMWARE="'+' '.join(p for p in self.firmware if not p.startswith('qcom/'))+'"\n'
        (self.bundle/('config-'+self.rel)).write_text(self.config)
        fixture=load('kernel_dtb_fixture',Path(__file__).with_name('test_rp6_paddles.py'))
        self.paddles=load('kernel_paddles',REPO/'scripts/fix-rp6-paddles.py')
        self.trees=[]
        for name in ('Retroid Pocket 6','Retroid Pocket 6 TOP-DPAD'):
            tree,_=self.paddles.fix_tree(fixture.dtb(name),False)
            path = self.folder / 'dtb'; path.write_bytes(tree)
            subprocess.run(['fdtput','-c',str(path),'/soc@0/mmc@8804000'],check=True)
            subprocess.run(['fdtput','-t','s',str(path),'/soc@0/mmc@8804000','status','okay'],check=True)
            subprocess.run(['fdtput','-t','i',str(path),'/soc@0/mmc@8804000','bus-width','4'],check=True)
            tree = path.read_bytes()
            self.trees.append(tree)
        (self.bundle/'boot').mkdir()
        self.pack()

    def pack(self, *, missing_firmware=False, stale_config=False):
        cpio=load('kernel_cpio',REPO/'scripts/repack-rp6-initramfs.py')
        entries=[]
        for inode,(name,data) in enumerate(self.init.items(),1):
            fields=[inode,0o100755 if name in ('init','konkr-update-recover','bootdebug','bin/busybox') else 0o100644,0,0,1,0,0,0,0,0,0,0,0]
            entries.append((name,fields,data))
        embedded=b'Linux version '+self.rel.encode()+b' fixture\0'+cpio.write_cpio(entries)
        embedded+=b'IKCFG_ST'+gzip.compress((self.config if not stale_config else self.config.replace('OVERLAY_FS=y','OVERLAY_FS=m')).encode(),mtime=0)+b'IKCFG_ED'
        for path,data in self.firmware.items():
            if not path.startswith('qcom/') and not (missing_firmware and path.endswith('board-2.bin')):
                embedded+=path.encode()+b'\0'+data
        payload=self.folder/'payload';payload.write_bytes(gzip.compress(embedded,mtime=0)+b''.join(self.trees))
        subprocess.run(['python3',str(REPO/'external-and-mods/kernel-common/mkbootimg-v0.py'),
                        '--kernel',str(payload),'--out',str(self.bundle/'boot/KERNEL')],check=True,stdout=subprocess.DEVNULL)

    def invoke(self):
        return subprocess.run(['python3',str(TOOL),'artifacts','--lock',str(self.lockfile),
                               '--kernel-dir',str(self.bundle)],capture_output=True,text=True)

    def test_complete_matching_bundle_passes(self):
        r=self.invoke();self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['kernel_release'],self.rel)

    def test_rejects_mismatched_module_vermagic(self):
        self.mod.write_bytes(self.mod.read_bytes().replace(self.rel.encode(),b'7.0.14-edge-sm8550'))
        r=self.invoke();self.assertNotEqual(r.returncode,0);self.assertIn('vermagic',r.stderr)

    def test_rejects_missing_rp6_top_dpad(self):
        self.trees.pop();self.pack()
        r=self.invoke();self.assertNotEqual(r.returncode,0);self.assertIn('DTB',r.stderr)

    def test_rejects_missing_builtin_firmware(self):
        self.pack(missing_firmware=True)
        r=self.invoke();self.assertNotEqual(r.returncode,0);self.assertIn('built-in firmware',r.stderr)

    def test_rejects_wrong_root_firmware(self):
        (self.bundle/'firmware/qcom/a740_sqe.fw').write_bytes(b'wrong GPU microcode')
        r=self.invoke();self.assertNotEqual(r.returncode,0);self.assertIn('firmware SHA256',r.stderr)

    def test_rejects_stale_embedded_initramfs(self):
        self.init['mount-etc-overlay']=b'old early /etc';self.pack()
        r=self.invoke();self.assertNotEqual(r.returncode,0);self.assertIn('initramfs',r.stderr)

    def test_rejects_config_different_from_packed_kernel(self):
        self.pack(stale_config=True)
        r=self.invoke();self.assertNotEqual(r.returncode,0);self.assertIn('embedded config',r.stderr)


if __name__=='__main__':unittest.main()
