import datetime
import os
import glob

from django.conf import settings
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse
from model_mommy import mommy
import xlrd

from evap.evaluation.models import Semester, UserProfile, Course, CourseType, TextAnswer, Contribution, \
                                   Questionnaire, Question, EmailTemplate, Degree, FaqSection, FaqQuestion
from evap.evaluation.tests.tools import FuzzyInt, WebTest, ViewTest
from evap.staff.tools import generate_import_filename


def helper_delete_all_import_files(user_id):
    file_filter = generate_import_filename(user_id, "*")
    for filename in glob.glob(file_filter):
        os.remove(filename)


# Staff - Root View
class TestStaffIndexView(ViewTest):
    test_users = ['staff']
    url = '/staff/'

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])


# Staff - FAQ View
class TestStaffFAQView(ViewTest):
    url = '/staff/faq/'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])


class TestStaffFAQEditView(ViewTest):
    url = '/staff/faq/1'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        section = mommy.make(FaqSection)
        mommy.make(FaqQuestion, section=section)


# Staff - User Views
class TestUserIndexView(ViewTest):
    url = '/staff/user/'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_num_queries_is_constant(self):
        """
            ensures that the number of queries in the user list is constant
            and not linear to the number of users
        """
        num_users = 50
        semester = mommy.make(Semester, is_archived=True)
        course = mommy.make(Course, state="published", semester=semester, _participant_count=1, _voter_count=1)  # this triggers more checks in UserProfile.can_staff_delete
        mommy.make(UserProfile, _quantity=num_users, courses_participating_in=[course])

        with self.assertNumQueries(FuzzyInt(0, num_users - 1)):
            self.app.get(self.url, user="staff")


class TestUserCreateView(ViewTest):
    url = "/staff/user/create"
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_user_is_created(self):
        page = self.get_assert_200(self.url, "staff")
        form = page.forms["user-form"]
        form["username"] = "mflkd862xmnbo5"
        form["first_name"] = "asd"
        form["last_name"] = "asd"
        form["email"] = "a@b.de"

        form.submit()

        self.assertEqual(UserProfile.objects.order_by("pk").last().username, "mflkd862xmnbo5")


class TestUserBulkDeleteView(ViewTest):
    url = '/staff/user/bulk_delete'
    test_users = ['staff']
    filename = os.path.join(settings.BASE_DIR, 'staff/fixtures/test_user_bulk_delete_file.txt')

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_testrun_deletes_no_users(self):
        page = self.app.get(self.url, user='staff')
        form = page.forms['user-bulk-delete-form']

        form['username_file'] = (self.filename,)

        users_before = UserProfile.objects.count()

        reply = form.submit(name='operation', value='test')

        # Not getting redirected after.
        self.assertEqual(reply.status_code, 200)
        # No user got deleted.
        self.assertEqual(users_before, UserProfile.objects.count())

    def test_deletes_users(self):
        mommy.make(UserProfile, username='testuser1')
        mommy.make(UserProfile, username='testuser2')
        contribution = mommy.make(Contribution)
        mommy.make(UserProfile, username='contributor', contributions=[contribution])
        page = self.app.get(self.url, user='staff')
        form = page.forms["user-bulk-delete-form"]

        form["username_file"] = (self.filename,)

        self.assertEqual(UserProfile.objects.filter(username__in=['testuser1', 'testuser2', 'contributor']).count(), 3)
        user_count_before = UserProfile.objects.count()

        reply = form.submit(name="operation", value="bulk_delete")

        # Getting redirected after.
        self.assertEqual(reply.status_code, 302)

        # Assert only one user got deleted.
        self.assertTrue(UserProfile.objects.filter(username='testuser1').exists())
        self.assertFalse(UserProfile.objects.filter(username='testuser2').exists())
        self.assertTrue(UserProfile.objects.filter(username='contributor').exists())
        self.assertEqual(UserProfile.objects.count(), user_count_before - 1)


class TestUserImportView(ViewTest):
    url = "/staff/user/import"
    test_users = ["staff"]
    filename_valid = os.path.join(settings.BASE_DIR, "staff/fixtures/valid_user_import.xls")
    filename_invalid = os.path.join(settings.BASE_DIR, "staff/fixtures/invalid_user_import.xls")
    filename_random = os.path.join(settings.BASE_DIR, "staff/fixtures/random.random")

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username="staff", groups=[Group.objects.get(name="Staff")])

    def test_import_valid_file(self):
        page = self.app.get(self.url, user='staff')

        original_user_count = UserProfile.objects.count()

        form = page.forms["user-import-form"]
        form["excel_file"] = (self.filename_valid,)
        page = form.submit(name="operation", value="test")

        self.assertContains(page, 'Import previously uploaded file')
        self.assertEqual(UserProfile.objects.count(), original_user_count)

        form = page.forms["user-import-form"]
        form.submit(name="operation", value="import")
        self.assertEqual(UserProfile.objects.count(), original_user_count + 2)

        page = self.app.get(self.url, user='staff')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_error_handling(self):
        """
        Tests whether errors given from the importer are displayed
        """
        page = self.app.get(self.url, user='staff')

        original_user_count = UserProfile.objects.count()

        form = page.forms["user-import-form"]
        form["excel_file"] = (self.filename_invalid,)

        reply = form.submit(name="operation", value="test")

        self.assertContains(reply, 'Sheet &quot;Sheet1&quot;, row 2: Email address is missing.')
        self.assertContains(reply, 'Errors occurred while parsing the input data. No data was imported.')
        self.assertNotContains(reply, 'Import previously uploaded file')

        self.assertEqual(UserProfile.objects.count(), original_user_count)

    def test_warning_handling(self):
        """
        Tests whether warnings given from the importer are displayed
        """
        mommy.make(UserProfile, email="42@42.de", username="lucilia.manilium")

        page = self.app.get(self.url, user='staff')

        form = page.forms["user-import-form"]
        form["excel_file"] = (self.filename_valid,)

        reply = form.submit(name="operation", value="test")
        self.assertContains(reply, "The existing user would be overwritten with the following data:<br>"
                " - lucilia.manilium ( None None, 42@42.de) (existing)<br>"
                " - lucilia.manilium ( Lucilia Manilium, lucilia.manilium@institution.example.com) (new)")

    def test_suspicious_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["user-import-form"]
        form["excel_file"] = (self.filename_valid,)

        # Should throw SuspiciousOperation Exception.
        reply = form.submit(name="operation", value="hackit", expect_errors=True)

        self.assertEqual(reply.status_code, 400)

    def test_invalid_upload_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["user-import-form"]
        page = form.submit(name="operation", value="test")

        self.assertContains(page, 'Please select an Excel file')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_invalid_import_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["user-import-form"]
        reply = form.submit(name="operation", value="import", expect_errors=True)

        self.assertEqual(reply.status_code, 400)


# Staff - Semester Views
class TestSemesterView(ViewTest):
    url = '/staff/semester/1'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.semester = mommy.make(Semester, pk=1)
        cls.course1 = mommy.make(Course, name_de="A - Course 1", name_en="B - Course 1", semester=cls.semester)
        cls.course2 = mommy.make(Course, name_de="B - Course 2", name_en="A - Course 2", semester=cls.semester)
        mommy.make(Contribution, course=cls.course1, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)
        mommy.make(Contribution, course=cls.course2, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)

    def test_view_list_sorting(self):
        page = self.app.get(self.url, user='staff', extra_environ={'HTTP_ACCEPT_LANGUAGE': 'en'}).body.decode("utf-8")
        position_course1 = page.find("Course 1")
        position_course2 = page.find("Course 2")
        self.assertGreater(position_course1, position_course2)

        page = self.app.get(self.url, user='staff', extra_environ={'HTTP_ACCEPT_LANGUAGE': 'de'}).body.decode("utf-8")
        position_course1 = page.find("Course 1")
        position_course2 = page.find("Course 2")
        self.assertLess(position_course1, position_course2)


class TestSemesterCreateView(ViewTest):
    url = '/staff/semester/create'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_create(self):
        name_de = 'name_de'
        name_en = 'name_en'

        response = self.app.get(self.url, user='staff')
        form = response.forms['semester-form']
        form['name_de'] = name_de
        form['name_en'] = name_en
        form.submit()

        self.assertEqual(Semester.objects.filter(name_de=name_de, name_en=name_en).count(), 1)


class TestSemesterEditView(ViewTest):
    url = '/staff/semester/1/edit'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.semester = mommy.make(Semester, pk=1, name_de='old_name', name_en='old_name')

    def test_name_change(self):
        new_name_de = 'new_name_de'
        new_name_en = 'new_name_en'
        self.assertNotEqual(self.semester.name_de, new_name_de)
        self.assertNotEqual(self.semester.name_en, new_name_en)

        response = self.app.get(self.url, user='staff')
        form = response.forms['semester-form']
        form['name_de'] = new_name_de
        form['name_en'] = new_name_en
        form.submit()

        self.semester.refresh_from_db()
        self.assertEqual(self.semester.name_de, new_name_de)
        self.assertEqual(self.semester.name_en, new_name_en)


class TestSemesterDeleteView(ViewTest):
    url = '/staff/semester/delete'
    csrf_checks = False

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_failure(self):
        semester = mommy.make(Semester, pk=1)
        mommy.make(Course, semester=semester, state='in_evaluation', voters=[mommy.make(UserProfile)])
        self.assertFalse(semester.can_staff_delete)
        response = self.app.post(self.url, params={'semester_id': 1}, user='staff', expect_errors=True)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Semester.objects.filter(pk=1).exists())

    def test_success(self):
        semester = mommy.make(Semester, pk=1)
        self.assertTrue(semester.can_staff_delete)
        response = self.app.post(self.url, params={'semester_id': 1}, user='staff')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Semester.objects.filter(pk=1).exists())


class TestSemesterLotteryView(ViewTest):
    url = '/staff/semester/1/lottery'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        mommy.make(Semester, pk=1)


class TestSemesterAssignView(ViewTest):
    url = '/staff/semester/1/assign'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        mommy.make(Semester, pk=1)


class TestSemesterTodoView(ViewTest):
    url = '/staff/semester/1/todo'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.semester = mommy.make(Semester, pk=1)

    def test_todo(self):
        course = mommy.make(Course, semester=self.semester, state='prepared', name_en='name_to_find', name_de='name_to_find')
        user = mommy.make(UserProfile, username='user_to_find')
        mommy.make(Contribution, course=course, contributor=user, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)

        response = self.app.get(self.url, user='staff')
        self.assertContains(response, 'user_to_find')
        self.assertContains(response, 'name_to_find')


class TestSemesterImportView(ViewTest):
    url = "/staff/semester/1/import"
    test_users = ["staff"]
    filename_valid = os.path.join(settings.BASE_DIR, "staff/fixtures/test_enrollment_data.xls")
    filename_invalid = os.path.join(settings.BASE_DIR, "staff/fixtures/invalid_enrollment_data.xls")
    filename_random = os.path.join(settings.BASE_DIR, "staff/fixtures/random.random")

    @classmethod
    def setUpTestData(cls):
        mommy.make(Semester, pk=1)
        mommy.make(UserProfile, username="staff", groups=[Group.objects.get(name="Staff")])

    def test_import_valid_file(self):
        mommy.make(CourseType, name_de="Vorlesung", name_en="Vorlesung")
        mommy.make(CourseType, name_de="Seminar", name_en="Seminar")

        original_user_count = UserProfile.objects.count()

        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        form["excel_file"] = (self.filename_valid,)
        page = form.submit(name="operation", value="test")

        self.assertEqual(UserProfile.objects.count(), original_user_count)

        form = page.forms["semester-import-form"]
        form['vote_start_date'] = "02/29/2000"
        form['vote_end_date'] = "02/29/2012"
        form.submit(name="operation", value="import")

        self.assertEqual(UserProfile.objects.count(), original_user_count + 23)

    def test_error_handling(self):
        """
        Tests whether errors given from the importer are displayed
        """
        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        form["excel_file"] = (self.filename_invalid,)

        reply = form.submit(name="operation", value="test")
        self.assertContains(reply, 'Sheet &quot;MA Belegungen&quot;, row 3: The users&#39;s data (email: bastius.quid@external.example.com) differs from it&#39;s data in a previous row.')
        self.assertContains(reply, 'Sheet &quot;MA Belegungen&quot;, row 7: Email address is missing.')
        self.assertContains(reply, 'The imported data contains two email addresses with the same username')
        self.assertContains(reply, 'Errors occurred while parsing the input data. No data was imported.')

        self.assertNotContains(page, 'Import previously uploaded file')

    def test_warning_handling(self):
        """
        Tests whether warnings given from the importer are displayed
        """
        mommy.make(UserProfile, email="42@42.de", username="lucilia.manilium")

        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        form["excel_file"] = (self.filename_valid,)

        reply = form.submit(name="operation", value="test")
        self.assertContains(reply, "The existing user would be overwritten with the following data:<br>"
                " - lucilia.manilium ( None None, 42@42.de) (existing)<br>"
                " - lucilia.manilium ( Lucilia Manilium, lucilia.manilium@institution.example.com) (new)")

    def test_suspicious_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        form["excel_file"] = (self.filename_valid,)

        # Should throw SuspiciousOperation Exception.
        reply = form.submit(name="operation", value="hackit", expect_errors=True)

        self.assertEqual(reply.status_code, 400)

    def test_invalid_upload_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        page = form.submit(name="operation", value="test")

        self.assertContains(page, 'Please select an Excel file')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_invalid_import_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        # invalid because no file has been uploaded previously (and the button doesn't even exist)
        reply = form.submit(name="operation", value="import", expect_errors=True)

        self.assertEqual(reply.status_code, 400)

    def test_missing_evaluation_period(self):
        mommy.make(CourseType, name_de="Vorlesung", name_en="Vorlesung")
        mommy.make(CourseType, name_de="Seminar", name_en="Seminar")

        page = self.app.get(self.url, user='staff')

        form = page.forms["semester-import-form"]
        form["excel_file"] = (self.filename_valid,)
        page = form.submit(name="operation", value="test")

        form = page.forms["semester-import-form"]
        page = form.submit(name="operation", value="import")

        self.assertContains(page, 'Please enter an evaluation period')
        self.assertContains(page, 'Import previously uploaded file')


class TestSemesterExportView(ViewTest):
    url = '/staff/semester/1/export'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.semester = mommy.make(Semester, pk=1)
        cls.course_type = mommy.make(CourseType)
        cls.course = mommy.make(Course, type=cls.course_type, semester=cls.semester)

    def test_view_excel_file_sorted(self):
        course1 = mommy.make(Course, state='published', type=self.course_type,
                             name_de='A - Course1', name_en='B - Course1', semester=self.semester)

        course2 = mommy.make(Course, state='published', type=self.course_type,
                             name_de='B - Course2', name_en='A - Course2', semester=self.semester)

        mommy.make(Contribution, course=course1, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)
        mommy.make(Contribution, course=course2, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)

        page = self.app.get(self.url, user='staff')
        form = page.forms["semester-export-form"]
        form.set('form-0-selected_course_types', 'id_form-0-selected_course_types_0')
        form.set('include_not_enough_answers', 'on')

        response_de = form.submit(extra_environ={'HTTP_ACCEPT_LANGUAGE': 'de'})
        response_en = form.submit(extra_environ={'HTTP_ACCEPT_LANGUAGE': 'en'})

        # Load responses as Excel files and check for correct sorting
        workbook = xlrd.open_workbook(file_contents=response_de.content)
        self.assertEqual(workbook.sheets()[0].row_values(0)[1], "A - Course1")
        self.assertEqual(workbook.sheets()[0].row_values(0)[3], "B - Course2")

        workbook = xlrd.open_workbook(file_contents=response_en.content)
        self.assertEqual(workbook.sheets()[0].row_values(0)[1], "A - Course2")
        self.assertEqual(workbook.sheets()[0].row_values(0)[3], "B - Course1")

    def test_view_downloads_excel_file(self):
        page = self.app.get(self.url, user='staff')
        form = page.forms["semester-export-form"]

        # Check one course type.
        form.set('form-0-selected_course_types', 'id_form-0-selected_course_types_0')

        response = form.submit()

        # Load response as Excel file and check its heading for correctness.
        workbook = xlrd.open_workbook(file_contents=response.content)
        self.assertEqual(workbook.sheets()[0].row_values(0)[0],
                         'Evaluation {0}\n\n{1}'.format(self.semester.name, ", ".join([self.course_type.name])))


class TestSemesterRawDataExportView(ViewTest):
    url = '/staff/semester/1/raw_export'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.student_user = mommy.make(UserProfile, username='student')
        cls.semester = mommy.make(Semester, pk=1)
        cls.course_type = mommy.make(CourseType, name_en="Type")
        cls.course1 = mommy.make(Course, type=cls.course_type, semester=cls.semester, participants=[cls.student_user],
            voters=[cls.student_user], name_de="Veranstaltung 1", name_en="Course 1")
        cls.course2 = mommy.make(Course, type=cls.course_type, semester=cls.semester, participants=[cls.student_user],
            name_de="Veranstaltung 2", name_en="Course 2")
        mommy.make(Contribution, course=cls.course1, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)
        mommy.make(Contribution, course=cls.course2, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)

    def test_view_downloads_csv_file(self):
        response = self.app.get(self.url, user='staff')
        expected_content = (
            "Name;Degrees;Type;Single result;State;#Voters;#Participants;#Comments;Average grade\r\n"
            "Course 1;;Type;False;new;1;1;0;\r\n"
            "Course 2;;Type;False;new;0;1;0;\r\n"
        )
        self.assertEqual(response.content, expected_content.encode("utf-8"))


class TestSemesterParticipationDataExportView(ViewTest):
    url = '/staff/semester/1/participation_export'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.student_user = mommy.make(UserProfile, username='student')
        cls.semester = mommy.make(Semester, pk=1)
        cls.course_type = mommy.make(CourseType, name_en="Type")
        cls.course1 = mommy.make(Course, type=cls.course_type, semester=cls.semester, participants=[cls.student_user],
            voters=[cls.student_user], name_de="Veranstaltung 1", name_en="Course 1", is_required_for_reward=True)
        cls.course2 = mommy.make(Course, type=cls.course_type, semester=cls.semester, participants=[cls.student_user],
            name_de="Veranstaltung 2", name_en="Course 2", is_required_for_reward=False)
        mommy.make(Contribution, course=cls.course1, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)
        mommy.make(Contribution, course=cls.course2, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)

    def test_view_downloads_csv_file(self):
        response = self.app.get(self.url, user='staff')
        expected_content = (
            "Username;Can use reward points;#Required courses voted for;#Required courses;#Optional courses voted for;"
            "#Optional courses;Earned reward points\r\n"
            "student;False;1;1;0;1;False\r\n")
        self.assertEqual(response.content, expected_content.encode("utf-8"))


class TestCourseOperationView(ViewTest):
    url = '/staff/semester/111/courseoperation'
    fixtures = ['minimal_test_data']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.semester = mommy.make(Semester, pk=111)

    def helper_semester_state_views(self, course_ids, old_state, new_state, operation):
        page = self.app.get("/staff/semester/1", user="evap")
        form = page.forms["form_" + old_state]
        for course_id in course_ids:
            self.assertIn(Course.objects.get(pk=course_id).state, old_state)
        form['course'] = course_ids
        response = form.submit('operation', value=operation)

        form = response.forms["course-operation-form"]
        response = form.submit()
        self.assertIn("Successfully", str(response))
        for course_id in course_ids:
            self.assertEqual(Course.objects.get(pk=course_id).state, new_state)

    """
        The following tests make sure the course state transitions are triggerable via the UI.
    """
    def test_semester_publish(self):
        self.helper_semester_state_views([7], "reviewed", "published", "publish")

    def test_semester_reset_1(self):
        self.helper_semester_state_views([2], "prepared", "new", "revertToNew")

    def test_semester_reset_2(self):
        self.helper_semester_state_views([4], "approved", "new", "revertToNew")

    def test_semester_approve_1(self):
        self.helper_semester_state_views([1], "new", "approved", "approve")

    def test_semester_approve_2(self):
        self.helper_semester_state_views([2], "prepared", "approved", "approve")

    def test_semester_approve_3(self):
        self.helper_semester_state_views([3], "editor_approved", "approved", "approve")

    def test_semester_contributor_ready_1(self):
        self.helper_semester_state_views([1, 10], "new", "prepared", "prepare")

    def test_semester_contributor_ready_2(self):
        self.helper_semester_state_views([3], "editor_approved", "prepared", "reenableEditorReview")

    def test_semester_unpublish(self):
        self.helper_semester_state_views([8], "published", "reviewed", "unpublish")

    def test_operation_start_evaluation(self):
        urloptions = '?course=1&operation=startEvaluation'
        mommy.make(Course, pk=1, state='approved', semester=self.semester)

        response = self.app.get(self.url + urloptions, user='staff')
        self.assertEqual(response.status_code, 200, 'url "{}" failed with user "staff"'.format(self.url))

        form = response.forms['course-operation-form']
        form.submit()

        course = Course.objects.get(pk=1)
        self.assertEqual(course.state, 'in_evaluation')

    def test_operation_prepare(self):
        urloptions = '?course=1&operation=prepare'
        mommy.make(Course, pk=1, state='new', semester=self.semester)

        response = self.app.get(self.url + urloptions, user='staff')
        self.assertEqual(response.status_code, 200, 'url "{}" failed with user "staff"'.format(self.url))

        form = response.forms['course-operation-form']
        form.submit()

        course = Course.objects.get(pk=1)
        self.assertEqual(course.state, 'prepared')


class TestSingleResultCreateView(ViewTest):
    url = '/staff/semester/1/singleresult/create'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        mommy.make(Semester, pk=1)
        mommy.make(CourseType)

    def test_single_result_create(self):
        """
            Tests the single result creation view with one valid and one invalid input dataset.
        """
        response = self.get_assert_200(self.url, "staff")
        form = response.forms["single-result-form"]
        form["name_de"] = "qwertz"
        form["name_en"] = "qwertz"
        form["type"] = 1
        form["degrees"] = ["1"]
        form["event_date"] = "02/1/2014"
        form["answer_1"] = 6
        form["answer_3"] = 2
        # missing responsible to get a validation error

        form.submit()
        self.assertFalse(Course.objects.exists())

        form["responsible"] = self.staff_user.pk  # now do it right

        form.submit()
        self.assertEqual(Course.objects.get().name_de, "qwertz")


# Staff - Semester - Course Views
class TestCourseCreateView(ViewTest):
    url = '/staff/semester/1/course/create'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        mommy.make(Semester, pk=1)
        mommy.make(CourseType)
        mommy.make(Questionnaire, pk=1, is_for_contributors=False)
        mommy.make(Questionnaire, pk=2, is_for_contributors=True)

    def test_course_create(self):
        """
            Tests the course creation view with one valid and one invalid input dataset.
        """
        response = self.get_assert_200("/staff/semester/1/course/create", "staff")
        form = response.forms["course-form"]
        form["name_de"] = "lfo9e7bmxp1xi"
        form["name_en"] = "asdf"
        form["type"] = 1
        form["degrees"] = ["1"]
        form["vote_start_date"] = "02/1/2099"
        form["vote_end_date"] = "02/1/2014"  # wrong order to get the validation error
        form["general_questions"] = ["1"]

        form['contributions-TOTAL_FORMS'] = 1
        form['contributions-INITIAL_FORMS'] = 0
        form['contributions-MAX_NUM_FORMS'] = 5
        form['contributions-0-course'] = ''
        form['contributions-0-contributor'] = self.staff_user.pk
        form['contributions-0-questionnaires'] = [2]
        form['contributions-0-order'] = 0
        form['contributions-0-responsibility'] = "RESPONSIBLE"
        form['contributions-0-comment_visibility'] = "ALL"

        form.submit()
        self.assertFalse(Course.objects.exists())

        form["vote_start_date"] = "02/1/2014"
        form["vote_end_date"] = "02/1/2099"  # now do it right

        form.submit()
        self.assertEqual(Course.objects.get().name_de, "lfo9e7bmxp1xi")


class TestCourseEditView(ViewTest):
    url = '/staff/semester/1/course/1/edit'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        semester = mommy.make(Semester, pk=1)
        course = mommy.make(Course, semester=semester, pk=1)

        # This is necessary so that the call to is_single_result does not fail.
        user = mommy.make(UserProfile)
        mommy.make(Contribution, course=course, contributor=user, responsible=True, can_edit=True, comment_visibility=Contribution.ALL_COMMENTS)

    def test_single_result(self):
        pass  # TODO: Should be done.


class TestCoursePreviewView(ViewTest):
    url = '/staff/semester/1/course/1/preview'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        semester = mommy.make(Semester, pk=1)
        course = mommy.make(Course, semester=semester, pk=1)
        course.general_contribution.questionnaires.set([mommy.make(Questionnaire)])


class TestCourseImportPersonsView(ViewTest):
    url = "/staff/semester/1/course/1/person_import"
    test_users = ["staff"]
    filename_valid = os.path.join(settings.BASE_DIR, "staff/fixtures/valid_user_import.xls")
    filename_invalid = os.path.join(settings.BASE_DIR, "staff/fixtures/invalid_user_import.xls")
    filename_random = os.path.join(settings.BASE_DIR, "staff/fixtures/random.random")

    @classmethod
    def setUpTestData(cls):
        semester = mommy.make(Semester, pk=1)
        cls.staff_user = mommy.make(UserProfile, username="staff", groups=[Group.objects.get(name="Staff")])
        cls.course = mommy.make(Course, pk=1, semester=semester)
        profiles = mommy.make(UserProfile, _quantity=42)
        cls.course2 = mommy.make(Course, pk=2, semester=semester, participants=profiles)

    @classmethod
    def tearDown(cls):
        # delete the uploaded file again so other tests can start with no file guaranteed
        helper_delete_all_import_files(cls.staff_user.id)

    def test_import_valid_participants_file(self):
        page = self.app.get(self.url, user='staff')

        original_participant_count = self.course.participants.count()

        form = page.forms["participant-import-form"]
        form["excel_file"] = (self.filename_valid,)
        page = form.submit(name="operation", value="test-participants")

        self.assertContains(page, 'Import previously uploaded file')
        self.assertEqual(self.course.participants.count(), original_participant_count)

        form = page.forms["participant-import-form"]
        form.submit(name="operation", value="import-participants")
        self.assertEqual(self.course.participants.count(), original_participant_count + 2)

        page = self.app.get(self.url, user='staff')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_copy_participants(self):
        page = self.app.get(self.url, user='staff')

        original_participant_count = self.course.participants.count()

        form = page.forms["participant-copy-form"]
        form["course"] = str(self.course2.pk)
        page = form.submit(name="operation", value="copy-participants")

        self.assertEqual(self.course.participants.count(), original_participant_count + self.course2.participants.count())

    def test_import_valid_contributors_file(self):
        page = self.app.get(self.url, user='staff')

        original_contributor_count = UserProfile.objects.filter(contributions__course=self.course).count()

        form = page.forms["contributor-import-form"]
        form["excel_file"] = (self.filename_valid,)
        page = form.submit(name="operation", value="test-contributors")

        self.assertContains(page, 'Import previously uploaded file')
        self.assertEqual(UserProfile.objects.filter(contributions__course=self.course).count(), original_contributor_count)

        form = page.forms["contributor-import-form"]
        form.submit(name="operation", value="import-contributors")
        self.assertEqual(UserProfile.objects.filter(contributions__course=self.course).count(), original_contributor_count + 2)

        page = self.app.get(self.url, user='staff')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_copy_contributors(self):
        page = self.app.get(self.url, user='staff')

        original_contributor_count = UserProfile.objects.filter(contributions__course=self.course).count()

        form = page.forms["contributor-copy-form"]
        form["course"] = str(self.course2.pk)
        page = form.submit(name="operation", value="copy-contributors")

        new_contributor_count = UserProfile.objects.filter(contributions__course=self.course).count()
        self.assertEqual(new_contributor_count, original_contributor_count + UserProfile.objects.filter(contributions__course=self.course2).count())

    def test_import_participants_error_handling(self):
        """
        Tests whether errors given from the importer are displayed
        """
        page = self.app.get(self.url, user='staff')

        form = page.forms["participant-import-form"]
        form["excel_file"] = (self.filename_invalid,)

        reply = form.submit(name="operation", value="test-participants")

        self.assertContains(reply, 'Sheet &quot;Sheet1&quot;, row 2: Email address is missing.')
        self.assertContains(reply, 'Errors occurred while parsing the input data. No data was imported.')
        self.assertNotContains(reply, 'Import previously uploaded file')

    def test_import_participants_warning_handling(self):
        """
        Tests whether warnings given from the importer are displayed
        """
        mommy.make(UserProfile, email="42@42.de", username="lucilia.manilium")

        page = self.app.get(self.url, user='staff')

        form = page.forms["participant-import-form"]
        form["excel_file"] = (self.filename_valid,)

        reply = form.submit(name="operation", value="test-participants")
        self.assertContains(reply, "The existing user would be overwritten with the following data:<br>"
                " - lucilia.manilium ( None None, 42@42.de) (existing)<br>"
                " - lucilia.manilium ( Lucilia Manilium, lucilia.manilium@institution.example.com) (new)")

    def test_import_contributors_error_handling(self):
        """
        Tests whether errors given from the importer are displayed
        """
        page = self.app.get(self.url, user='staff')

        form = page.forms["contributor-import-form"]
        form["excel_file"] = (self.filename_invalid,)

        reply = form.submit(name="operation", value="test-contributors")

        self.assertContains(reply, 'Sheet &quot;Sheet1&quot;, row 2: Email address is missing.')
        self.assertContains(reply, 'Errors occurred while parsing the input data. No data was imported.')
        self.assertNotContains(reply, 'Import previously uploaded file')

    def test_import_contributors_warning_handling(self):
        """
        Tests whether warnings given from the importer are displayed
        """
        mommy.make(UserProfile, email="42@42.de", username="lucilia.manilium")

        page = self.app.get(self.url, user='staff')

        form = page.forms["contributor-import-form"]
        form["excel_file"] = (self.filename_valid,)

        reply = form.submit(name="operation", value="test-contributors")
        self.assertContains(reply, "The existing user would be overwritten with the following data:<br>"
                " - lucilia.manilium ( None None, 42@42.de) (existing)<br>"
                " - lucilia.manilium ( Lucilia Manilium, lucilia.manilium@institution.example.com) (new)")

    def test_suspicious_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["participant-import-form"]
        form["excel_file"] = (self.filename_valid,)

        # Should throw SuspiciousOperation Exception.
        reply = form.submit(name="operation", value="hackit", expect_errors=True)

        self.assertEqual(reply.status_code, 400)

    def test_invalid_contributor_upload_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["contributor-import-form"]
        page = form.submit(name="operation", value="test-contributors")

        self.assertContains(page, 'Please select an Excel file')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_invalid_participant_upload_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["participant-import-form"]
        page = form.submit(name="operation", value="test-participants")

        self.assertContains(page, 'Please select an Excel file')
        self.assertNotContains(page, 'Import previously uploaded file')

    def test_invalid_contributor_import_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["contributor-import-form"]
        # invalid because no file has been uploaded previously (and the button doesn't even exist)
        reply = form.submit(name="operation", value="import-contributors", expect_errors=True)

        self.assertEqual(reply.status_code, 400)

    def test_invalid_participant_import_operation(self):
        page = self.app.get(self.url, user='staff')

        form = page.forms["participant-import-form"]
        # invalid because no file has been uploaded previously (and the button doesn't even exist)
        reply = form.submit(name="operation", value="import-participants", expect_errors=True)

        self.assertEqual(reply.status_code, 400)


class TestCourseEmailView(ViewTest):
    url = '/staff/semester/1/course/1/email'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        semester = mommy.make(Semester, pk=1)
        participant1 = mommy.make(UserProfile, email="foo@example.com")
        participant2 = mommy.make(UserProfile, email="bar@example.com")
        mommy.make(Course, pk=1, semester=semester, participants=[participant1, participant2])

    def test_emails_are_sent(self):
        page = self.get_assert_200(self.url, user="staff")
        form = page.forms["course-email-form"]
        form.get("recipients", index=0).checked = True  # send to all participants
        form["subject"] = "asdf"
        form["body"] = "asdf"
        form.submit()

        self.assertEqual(len(mail.outbox), 2)


class TestCourseCommentView(ViewTest):
    url = '/staff/semester/1/course/1/comments'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        semester = mommy.make(Semester, pk=1)
        cls.course = mommy.make(Course, semester=semester)

    def test_comments_showing_up(self):
        questionnaire = mommy.make(Questionnaire)
        question = mommy.make(Question, questionnaire=questionnaire, type='T')
        contribution = mommy.make(Contribution, course=self.course, contributor=mommy.make(UserProfile), questionnaires=[questionnaire])
        mommy.make(TextAnswer, contribution=contribution, question=question, original_answer='should show up')
        response = self.app.get(self.url, user='staff')

        self.assertContains(response, 'should show up')


class TestCourseCommentEditView(ViewTest):
    url = '/staff/semester/1/course/1/comment/1/edit'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        semester = mommy.make(Semester, pk=1)
        course = mommy.make(Course, semester=semester, pk=1)
        questionnaire = mommy.make(Questionnaire)
        question = mommy.make(Question, questionnaire=questionnaire, type='T')
        contribution = mommy.make(Contribution, course=course, contributor=mommy.make(UserProfile), questionnaires=[questionnaire])
        mommy.make(TextAnswer, contribution=contribution, question=question, original_answer='test answer text', pk=1)

    def test_comments_showing_up(self):
        response = self.app.get(self.url, user='staff')

        form = response.forms['comment-edit-form']
        self.assertEqual(form['original_answer'].value, 'test answer text')
        form['reviewed_answer'] = 'edited answer text'
        form.submit()

        answer = TextAnswer.objects.get(pk=1)
        self.assertEqual(answer.reviewed_answer, 'edited answer text')


# Staff Questionnaire Views
class TestQuestionnaireNewVersionView(ViewTest):
    url = '/staff/questionnaire/2/new_version'
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        cls.name_de_orig = 'kurzer name'
        cls.name_en_orig = 'short name'
        questionnaire = mommy.make(Questionnaire, id=2, name_de=cls.name_de_orig, name_en=cls.name_en_orig)
        mommy.make(Question, questionnaire=questionnaire)
        mommy.make(UserProfile, username="staff", groups=[Group.objects.get(name="Staff")])

    def test_changes_old_title(self):
        page = self.app.get(url=self.url, user='staff')
        form = page.forms['questionnaire-form']

        form.submit()

        timestamp = datetime.date.today()
        new_name_de = '{} (until {})'.format(self.name_de_orig, str(timestamp))
        new_name_en = '{} (until {})'.format(self.name_en_orig, str(timestamp))

        self.assertTrue(Questionnaire.objects.filter(name_de=self.name_de_orig, name_en=self.name_en_orig).exists())
        self.assertTrue(Questionnaire.objects.filter(name_de=new_name_de, name_en=new_name_en).exists())

    def test_no_second_update(self):

        # First save.
        page = self.app.get(url=self.url, user='staff')
        form = page.forms['questionnaire-form']
        form.submit()

        # Second try.
        new_questionnaire = Questionnaire.objects.get(name_de=self.name_de_orig)
        page = self.app.get(url='/staff/questionnaire/{}/new_version'.format(new_questionnaire.id), user='staff')

        # We should get redirected back to the questionnaire index.
        self.assertEqual(page.status_code, 302)  # REDIRECT
        self.assertEqual(page.location, '/staff/questionnaire/')


class TestQuestionnaireDeletionView(WebTest):
    url = "/staff/questionnaire/delete"
    csrf_checks = False

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        questionnaire1 = mommy.make(Questionnaire, pk=1)
        mommy.make(Questionnaire, pk=2)
        mommy.make(Contribution, questionnaires=[questionnaire1])

    def test_questionnaire_deletion(self):
        """
            Tries to delete two questionnaires via the respective post request,
            only the second attempt should succeed.
        """
        self.assertFalse(Questionnaire.objects.get(pk=1).can_staff_delete)
        response = self.app.post("/staff/questionnaire/delete", params={"questionnaire_id": 1}, user="staff", expect_errors=True)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Questionnaire.objects.filter(pk=1).exists())

        self.assertTrue(Questionnaire.objects.get(pk=2).can_staff_delete)
        response = self.app.post("/staff/questionnaire/delete", params={"questionnaire_id": 2}, user="staff")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Questionnaire.objects.filter(pk=2).exists())


# Staff Course Types Views
class TestCourseTypeView(ViewTest):
    url = "/staff/course_types/"
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_page_displays_something(self):
        CourseType.objects.create(name_de='uZJcsl0rNc', name_en='uZJcsl0rNc')
        page = self.get_assert_200(self.url, user="staff")
        self.assertIn('uZJcsl0rNc', page)

    def test_course_type_form(self):
        """
            Adds a course type via the staff form and verifies that the type was created in the db.
        """
        page = self.get_assert_200(self.url, user="staff")
        form = page.forms["course-type-form"]
        last_form_id = int(form["form-TOTAL_FORMS"].value) - 1
        form["form-" + str(last_form_id) + "-name_de"].value = "Test"
        form["form-" + str(last_form_id) + "-name_en"].value = "Test"
        response = form.submit()
        self.assertIn("Successfully", str(response))

        self.assertTrue(CourseType.objects.filter(name_de="Test", name_en="Test").exists())


class TestCourseTypeMergeView(ViewTest):
    url = "/staff/course_types/1/merge/2"
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])
        cls.main_type = mommy.make(CourseType, pk=1, name_en="A course type")
        cls.other_type = mommy.make(CourseType, pk=2, name_en="Obsolete course type")
        mommy.make(Course, type=cls.main_type)
        mommy.make(Course, type=cls.other_type)

    def test_merge_works(self):
        page = self.get_assert_200(self.url, user="staff")
        form = page.forms["course-type-merge-form"]
        response = form.submit()
        self.assertIn("Successfully", str(response))

        self.assertFalse(CourseType.objects.filter(name_en="Obsolete course type").exists())
        self.assertEqual(Course.objects.filter(type=self.main_type).count(), 2)
        for course in Course.objects.all():
            self.assertTrue(course.type == self.main_type)


# Other Views
class TestCourseCommentsUpdatePublishView(WebTest):
    url = reverse("staff:course_comments_update_publish")
    csrf_checks = False

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username="staff.user", groups=[Group.objects.get(name="Staff")])
        mommy.make(Course, pk=1)

    def helper(self, old_state, expected_new_state, action):
        textanswer = mommy.make(TextAnswer, state=old_state)
        response = self.app.post(self.url, params={"id": textanswer.id, "action": action, "course_id": 1}, user="staff.user")
        self.assertEqual(response.status_code, 200)
        textanswer.refresh_from_db()
        self.assertEqual(textanswer.state, expected_new_state)

    def test_review_actions(self):
        self.helper(TextAnswer.NOT_REVIEWED, TextAnswer.PUBLISHED, "publish")
        self.helper(TextAnswer.NOT_REVIEWED, TextAnswer.HIDDEN, "hide")
        self.helper(TextAnswer.NOT_REVIEWED, TextAnswer.PRIVATE, "make_private")
        self.helper(TextAnswer.PUBLISHED, TextAnswer.NOT_REVIEWED, "unreview")


class ArchivingTests(WebTest):

    def test_raise_403(self):
        """
            Tests whether inaccessible views on archived semesters/courses correctly raise a 403.
        """
        semester = mommy.make(Semester, is_archived=True)

        semester_url = "/staff/semester/{}/".format(semester.pk)

        self.get_assert_403(semester_url + "import", "evap")
        self.get_assert_403(semester_url + "assign", "evap")
        self.get_assert_403(semester_url + "course/create", "evap")
        self.get_assert_403(semester_url + "courseoperation", "evap")


class TestTemplateEditView(ViewTest):
    url = "/staff/template/1"
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_emailtemplate(self):
        """
            Tests the emailtemplate view with one valid and one invalid input datasets.
        """
        page = self.get_assert_200(self.url, "staff")
        form = page.forms["template-form"]
        form["subject"] = "subject: mflkd862xmnbo5"
        form["body"] = "body: mflkd862xmnbo5"
        form.submit()

        self.assertEqual(EmailTemplate.objects.get(pk=1).body, "body: mflkd862xmnbo5")

        form["body"] = " invalid tag: {{}}"
        form.submit()
        self.assertEqual(EmailTemplate.objects.get(pk=1).body, "body: mflkd862xmnbo5")


class TestDegreeView(ViewTest):
    url = "/staff/degrees/"
    test_users = ['staff']

    @classmethod
    def setUpTestData(cls):
        mommy.make(UserProfile, username='staff', groups=[Group.objects.get(name='Staff')])

    def test_degree_form(self):
        """
            Adds a degree via the staff form and verifies that the degree was created in the db.
        """
        page = self.get_assert_200(self.url, user="staff")
        form = page.forms["degree-form"]
        last_form_id = int(form["form-TOTAL_FORMS"].value) - 1
        form["form-" + str(last_form_id) + "-name_de"].value = "Test"
        form["form-" + str(last_form_id) + "-name_en"].value = "Test"
        response = form.submit()
        self.assertIn("Successfully", str(response))

        self.assertTrue(Degree.objects.filter(name_de="Test", name_en="Test").exists())
