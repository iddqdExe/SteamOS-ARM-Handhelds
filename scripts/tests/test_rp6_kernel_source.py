"""Behavior checks against the actual patched C code and compiled RP6 DTBs.

Set RP6_KERNEL_SOURCE and RP6_KERNEL_DTBS in the ARM64 build container.
"""
import os
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


def function(text, name):
    start = text.index(name + '(')
    start = text.rfind('\n', 0, start) + 1
    brace = text.index('{', start); depth = 1; end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}'); end += 1
    return text[start:end]


@unittest.skipUnless(os.environ.get('RP6_KERNEL_SOURCE'), 'needs actual patched Linux source')
class KernelSourceTests(unittest.TestCase):
    def setUp(self):
        self.src = Path(os.environ['RP6_KERNEL_SOURCE'])

    def execute(self, program):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'check.c'; out = Path(d) / 'check'
            src.write_text(program)
            subprocess.run(['gcc', '-Wall', '-Werror', str(src), '-o', str(out)], check=True)
            r = subprocess.run([str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_gpu_priority_maps_high_normal_low(self):
        gpu = (self.src / 'drivers/gpu/drm/msm/msm_gpu.h').read_text()
        sched = (self.src / 'include/drm/gpu_scheduler.h').read_text()
        submit = (self.src / 'drivers/gpu/drm/msm/msm_submitqueue.c').read_text()
        enum = re.search(r'enum drm_sched_priority\s*\{.*?\};', sched, re.S).group()
        macro = re.search(r'^#define NR_SCHED_PRIORITIES .*$', gpu, re.M).group()
        fn = function(gpu, 'msm_gpu_convert_priority')
        idx = re.search(r'unsigned idx\s*=\s*(.*?);', function(submit, 'get_sched_entity'), re.S).group(1)
        # Exercise the kernel function and entity-index expression for all rings.
        self.execute('#include <errno.h>\n#include <assert.h>\n' + enum + '\n' + macro + '''
struct msm_gpu { unsigned nr_rings; };
static unsigned div_u64_rem(unsigned long long n, unsigned d, unsigned *r) { *r=n%d; return n/d; }
''' + fn + '\nunsigned entity(unsigned ring_nr, enum drm_sched_priority sched_prio) { return ' + idx + '''; }
int main(void) {
  for (unsigned rings=1; rings<=4; rings++) {
    struct msm_gpu gpu={rings};
    for (unsigned p=0; p<rings*NR_SCHED_PRIORITIES; p++) {
      unsigned ring=99; enum drm_sched_priority sp=DRM_SCHED_PRIORITY_INVALID;
      assert(msm_gpu_convert_priority(&gpu,p,&ring,&sp)==0);
      assert(ring==p/NR_SCHED_PRIORITIES);
      assert(sp==DRM_SCHED_PRIORITY_HIGH+p%NR_SCHED_PRIORITIES);
      assert(entity(ring,sp)==p);
    }
    unsigned ring; enum drm_sched_priority sp;
    assert(msm_gpu_convert_priority(&gpu,rings*NR_SCHED_PRIORITIES,&ring,&sp)==-EINVAL);
    assert(msm_gpu_convert_priority(&gpu,-1,&ring,&sp)==-EINVAL);
  }
  return 0;
}''')
        vm = function(submit, 'msm_submitqueue_create')
        self.assertRegex(vm, r'drm_sched_entity_init\([^;]*DRM_SCHED_PRIORITY_KERNEL')

    def test_scan_start_serializes_computed_priority(self):
        text = (self.src / 'drivers/net/wireless/ath/ath12k/wmi.c').read_text()
        fn = function(text, 'ath12k_wmi_send_scan_start_cmd')
        start = fn.index('if (ar->state_11d')
        end = fn.index('ath12k_wmi_copy_scan_event_cntrl_flags', start)
        statements = fn[start:end]
        self.execute('''#include <assert.h>
#include <stdint.h>
#include <endian.h>
#define ATH12K_11D_PREPARING 1
#define WMI_SCAN_PRIORITY_LOW 1
#define WMI_SCAN_PRIORITY_MEDIUM 2
#define cpu_to_le32(x) htole32(x)
struct radio { unsigned state_11d; };
struct arg { unsigned scan_priority, notify_scan_events; };
struct cmd { uint32_t scan_priority, notify_scan_events; };
static void serialize(struct radio *ar, struct arg *arg, struct cmd *cmd) {
''' + statements + '''
}
int main(void) {
  for (unsigned state=0;state<=1;state++) {
    struct radio ar={state}; struct arg arg={0,17}; struct cmd cmd={0,0};
    serialize(&ar,&arg,&cmd);
    assert(le32toh(cmd.scan_priority)==(state?WMI_SCAN_PRIORITY_MEDIUM:WMI_SCAN_PRIORITY_LOW));
    assert(le32toh(cmd.notify_scan_events)==17);
  }
  return 0;
}''')


@unittest.skipUnless(os.environ.get('RP6_KERNEL_DTBS'), 'needs compiled RP6 DTBs')
class KernelDtbTests(unittest.TestCase):
    def test_both_rp6_dtbs_allow_sdr104(self):
        helper = Path(__file__).resolve().parents[1] / 'fix-rp6-paddles.py'
        spec = importlib.util.spec_from_file_location('paddles', helper)
        paddles = importlib.util.module_from_spec(spec); spec.loader.exec_module(paddles)
        for name in ('qcs8550-retroidpocket-rp6', 'qcs8550-retroidpocket-rp6-top-dpad'):
            dtb = Path(os.environ['RP6_KERNEL_DTBS']) / (name + '.dtb')
            props = paddles.properties(dtb.read_bytes())
            controller = props['/soc@0/mmc@8804000']
            self.assertNotIn('sdhci-caps-mask', controller, name)
            self.assertEqual(controller['bus-width'], paddles.cells(4))
            self.assertEqual(controller['status'], b'okay\0')
            paddles.verify_paddles(props)
            if os.environ.get('RP6_KERNEL_DTBS_BEFORE'):
                before = paddles.properties((Path(os.environ['RP6_KERNEL_DTBS_BEFORE']) / (name+'.dtb')).read_bytes())
                del before['/soc@0/mmc@8804000']['sdhci-caps-mask']
                self.assertEqual(props, before, 'SD change modified unrelated DTB values')


if __name__ == '__main__': unittest.main()
