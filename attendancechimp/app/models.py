"""
models.py — Data model for AttendanceChimp.

AttendanceChimp is an electronic class attendance tool.  Instructors create
courses and lectures; each lecture is assigned a random QR code.  Students
photograph the QR code and upload the image.  The system decodes the QR code,
matches it to a lecture, and records the attendance.

Entities
--------
- CourseProfile   : extends Django User → instructor-specific data
- StudentProfile  : extends Django User → student-specific data
- Course          : a course taught by one instructor
- Enrollment      : junction table linking students to courses
- Lecture         : a single class meeting (has a QR-code identifier)
- QRCodeUpload    : a student's uploaded QR-code photograph
"""

from django.db import models
from django.contrib.auth.models import User

import logging
import string
import random

logger = logging.getLogger(__name__) # set up tracking, auditing, and debugging
                                                               # allows using logger.warning(), logger.error(), 
                                                               # logger.info(), etc. Better than print() for debuggin... 


# ---------------------------------------------------------------------------
# User profiles
# ---------------------------------------------------------------------------

class StudentProfile(models.Model):
    '''
    Profile representing a student
    '''
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    student_id = models.CharField(max_length=8, blank=True)
    major = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"Student: {self.user.username}"

class InstructorProfile(models.Model):
    '''
    Profile representing an instructor
    '''
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='instructor_profile')
    department = models.CharField(max_length=100, blank=True)
    office_location = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"Instructor: {self.user.username} at {self.office_location}"

# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
class Course(models.Model):
    '''
    Represents an academic course taught by a single instructor
    '''
    course_id = models.CharField(max_length=20, unique=True, help_text="e.g., DATA13600")
    course_name = models.CharField(max_length=200)
    instructor = models.ForeignKey(InstructorProfile, on_delete=models.CASCADE, related_name="courses")
    meeting_schedule = models.CharField(max_length=200, help_text="e.g. MW 1:30PM - 2:50PM")
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.course_id}: {self.course_name}"

    
# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
class Enrollment(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")

    def __str__(self):
        return f"{self.student.user.username}: {self.course.code}"


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
class Lecture(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lectures")
    date = models.DateField()
    QRCode_id = models.CharField(max_length=256, unique=True)
    active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.course.name}, {self.date}"


# ---------------------------------------------------------------------------
# QR Code Upload
# ---------------------------------------------------------------------------
class QRCodeUpload(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="qr_uploads")
    lecture = models.ForeignKey(Lecture, on_delete=models.SET_NULL, null=True, blank=True, related_name="qr_uploads")
    image = models.ImageField(upload_to="qr_uploads/")
    uploaded_at = models.DateField(auto_now_add=True)
    verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.student.user.username}, {self.lecture.date}"

# ---------------------------------------------------------------------------
# Helper / API functions
# ---------------------------------------------------------------------------
