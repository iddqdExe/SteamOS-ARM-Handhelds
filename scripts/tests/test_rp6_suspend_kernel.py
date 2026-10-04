"""Exercise real UP-04 kernel callbacks and RP6 sleep DT contracts."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_rp6_kernel_source import function

@unittest.skipUnless(os.environ.get('RP6_KERNEL_SOURCE'), 'requires built Linux source')
class SuspendKernelTests(unittest.TestCase):
    def test_mcu_rail_state_and_failure_recovery(self):
        text=(Path(os.environ['RP6_KERNEL_SOURCE'])/'drivers/input/joystick/rsinput.c').read_text()
        suspend=function(text,'rsinput_suspend'); resume=function(text,'rsinput_resume')
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'check.c'; exe=Path(tmp)/'check'
            c.write_text('''#include <assert.h>
#include <stdbool.h>
#define dev_err(...) ((void)0)
struct rsinput_driver { bool vdd_off; void *vdd, *enable_gpio, *reset_gpio; };
struct device { struct rsinput_driver *drv; };
static int enabled=1, err_disable, err_enable, inits, err_init;
static void *dev_get_drvdata(struct device *d) { return d->drv; }
static void gpiod_set_value_cansleep(void *p,int v) { (void)p; (void)v; }
static int regulator_disable(void *p) { (void)p; if(err_disable)return err_disable; enabled--;return 0; }
static int regulator_enable(void *p) { (void)p; if(err_enable)return err_enable;enabled++;return 0; }
static int rsinput_init_commands(struct rsinput_driver *p) { (void)p; inits++;return err_init; }
''' + suspend + '\n' + resume + '''
int main(void) {
 struct rsinput_driver drv={0}; struct device dev={&drv};
 assert(!rsinput_suspend(&dev)); assert(enabled==0 && drv.vdd_off);
 assert(!rsinput_suspend(&dev)); assert(enabled==0);
 err_enable=-5; assert(rsinput_resume(&dev)==-5);assert(drv.vdd_off && inits==0);
 err_enable=0;assert(!rsinput_resume(&dev));assert(!drv.vdd_off && enabled==1 && inits==1);
 err_disable=-6;assert(rsinput_suspend(&dev)==-6);assert(!drv.vdd_off && enabled==1 && inits==2);
 err_disable=0;assert(!rsinput_suspend(&dev));err_init=-7;assert(rsinput_resume(&dev)==-7);
 assert(!drv.vdd_off && enabled==1);return 0;
}''')
            subprocess.run(['gcc','-Wall','-Werror',str(c),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
    def test_s2idle_mem_state_is_opt_in(self):
        src=Path(os.environ['RP6_KERNEL_SOURCE'])
        core=(src/'drivers/regulator/core.c').read_text()
        fn=function(core,'regulator_get_suspend_state')
        self.assertIn('s2idle_uses_state_mem',fn)
        rpmh=(src/'drivers/regulator/qcom-rpmh-regulator.c').read_text()
        self.assertIn('s2idle_uses_state_mem = true',rpmh)

@unittest.skipUnless(os.environ.get('RP6_KERNEL_DTBS'), 'requires compiled RP6 DTBs')
class SuspendDtbTests(unittest.TestCase):
    def test_rp6_wake_mcu_audio_and_pcie_sleep_floor(self):
        repo=Path(__file__).resolve().parents[2]
        spec=importlib.util.spec_from_file_location('paddles',repo/'scripts/fix-rp6-paddles.py')
        p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
        for name in ('qcs8550-retroidpocket-rp6','qcs8550-retroidpocket-rp6-top-dpad'):
            props=p.properties((Path(os.environ['RP6_KERNEL_DTBS'])/(name+'.dtb')).read_bytes())
            pad=next(v for v in props.values() if v.get('compatible')==b'gamepad,rsinput\0')
            rail=next(v for v in props.values() if v.get('regulator-name')==b'vdd_mcu_3v3\0')
            self.assertNotIn('regulator-always-on',rail)
            self.assertEqual(pad['vdd-supply'],rail['phandle'])
            wake=[v['wake-gpios'] for v in props.values() if 'wake-gpios' in v]
            self.assertTrue(any(w[-8:]==p.cells(96,1) for w in wake))
            for railname in (b'vreg_l15b_1p8\0',b'vreg_bob1\0'):
                path=next(k for k,v in props.items() if v.get('regulator-name')==railname)
                mem=props[path+'/regulator-state-mem']
                self.assertIn('regulator-on-in-suspend',mem)
                self.assertEqual(mem['regulator-mode'],p.cells(1))
            floor=[v for k,v in props.items() if k.endswith('/opp-suspend-1')]
            self.assertTrue(floor)
            self.assertIn('opp-suspend',floor[0]);self.assertEqual(floor[0]['opp-peak-kBps'],p.cells(1000,1))
            p.verify_paddles(props)

@unittest.skipUnless(os.environ.get('RP6_KERNEL_SOURCE'), 'requires Linux source')
class UartSuspendTests(unittest.TestCase):
    def test_failed_uart_suspend_balances_non_console_irq(self):
        text=(Path(os.environ['RP6_KERNEL_SOURCE'])/'drivers/tty/serial/qcom_geni_serial.c').read_text()
        fn=function(text,'qcom_geni_serial_suspend')
        program='''#include <assert.h>
struct qcom_geni_private_data { void *drv; };
struct uart_port { void *private_data; int irq, console; };
struct qcom_geni_serial_port { struct uart_port uport; int se; };
struct device { struct qcom_geni_serial_port *port; };
static int masked, error;
#define QCOM_ICC_TAG_ACTIVE_ONLY 1
static void *dev_get_drvdata(struct device *d) { return d->port; }
static int uart_console(struct uart_port *p) { return p->console; }
static void disable_irq(int i) { (void)i;masked++; }
static void __attribute__((unused)) enable_irq(int i) { (void)i;masked--; }
static void geni_icc_set_tag(void *p,int t) { (void)p;(void)t; }
static void geni_icc_set_bw(void *p) { (void)p; }
static int uart_suspend_port(void *d,struct uart_port *p) { (void)d;(void)p;return error; }
'''+fn+'''
int main(void) {
 struct qcom_geni_private_data data={0};
 struct qcom_geni_serial_port port={{&data,1,0},0};struct device dev={&port};
 error=-5;assert(qcom_geni_serial_suspend(&dev)==-5);assert(masked==0);
 error=0;assert(!qcom_geni_serial_suspend(&dev));assert(masked==1);
 masked=0;port.uport.console=1;assert(!qcom_geni_serial_suspend(&dev));assert(masked==0);
 return 0;
}'''
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'uart.c';exe=Path(tmp)/'uart';c.write_text(program)
            subprocess.run(['gcc','-Wall','-Werror',str(c),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
