import unittest
from unittest.mock import patch

from trust_provider import issue_phc


class TpApplicationBriefTests(unittest.TestCase):
    def test_dashboard_has_submitted_basic_information_without_full_document(self):
        application={
            'request_id':'request-1','status':'pending','created_at':'2026-10-16T10:00:00Z',
            'pt':{'PII':{'name':'测试用户','id_number':'identity-12345678',
                         'id_card_number':'123456789012345678','email':'person@example.test'}},
            'checks':{'signature_valid':True,'face_verified':False},
        }
        with patch.object(issue_phc,'_tpapp_list',return_value=[application]):
            item=issue_phc.list_phc_applications()['items'][0]
        self.assertEqual(item['name'],'测试用户')
        self.assertEqual(item['email'],'person@example.test')
        self.assertEqual(item['id_card_number_masked'],'****5678')
        self.assertNotIn('123456789012345678',str(item))
        self.assertIs(item['face_verified'],False)


if __name__=='__main__': unittest.main()
