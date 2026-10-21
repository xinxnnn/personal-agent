import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from app import runtime_watchdog as wd

class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.process=MagicMock();self.process.poll.return_value=None
        self.job={'stage':'ready','desired_running':True,'ever_ready':True,'process':self.process,'restarts':0}
        self.rt=SimpleNamespace(LOCK=threading.RLock(),STOPPING=threading.Event(),JOBS={'test':self.job},
                                 kill=MagicMock(),record_agent_lifecycle=MagicMock())
        self.restart=MagicMock()
        self.time=1000
    def tick(self,healthy):
        with patch.object(wd,'probe',return_value=healthy):
            wd.inspect_once(self.rt,clock=lambda:self.time,restart=self.restart)
    def test_three_failures_then_delayed_single_restart(self):
        self.tick(False);self.tick(False)
        self.assertEqual(self.job['stage'],'ready')
        self.tick(False)
        self.assertEqual(self.job['stage'],'recovering')
        self.tick(False);self.restart.assert_not_called()
        self.time+=10;self.tick(False);self.tick(False)
        self.restart.assert_called_once_with('test',self.job)
        self.rt.kill.assert_called_once_with(self.process)
        self.rt.record_agent_lifecycle.assert_called_once_with('test','agent_stopped')
    def test_success_clears_transient_failures(self):
        self.tick(False);self.tick(True);self.tick(False)
        self.assertEqual(self.job['health_failures'],1)
    def test_manual_stop_and_deleted_jobs_not_restarted(self):
        self.job['desired_running']=False
        for _ in range(5):self.tick(False)
        self.restart.assert_not_called()
        self.rt.JOBS.clear();self.tick(False);self.rt.kill.assert_not_called()
    def test_restart_limit(self):
        self.job['restarts']=3
        for _ in range(3):self.tick(False)
        self.assertFalse(self.job['desired_running'])
        self.assertEqual(self.job['stage'],'error')
        self.restart.assert_not_called()
    def test_stable_runtime_resets_budget(self):
        self.job.update(healthy_since=1,restarts=2)
        self.tick(True)
        self.assertEqual(self.job['restarts'],0)
    def test_unproven_initial_deployment_not_retried(self):
        self.job.update(stage='error',ever_ready=False)
        for _ in range(5):self.tick(False)
        self.restart.assert_not_called()
    def test_stop_during_probe_wins(self):
        def stop_during_probe(job):
            job.update(desired_running=False,stage='idle')
            return False
        with patch.object(wd,'probe',side_effect=stop_during_probe):
            wd.inspect_once(self.rt,clock=lambda:self.time,restart=self.restart)
        self.assertEqual(self.job['stage'],'idle')
        self.restart.assert_not_called()

if __name__=='__main__':unittest.main()
