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
from django.utils import timezone
 
import hashlib
import logging
import string
import random
 
logger = logging.getLogger(__name__)  # set up tracking, auditing, and debugging
# allows using logger.warning(), logger.error(),
# logger.info(), etc. Better than print() for debugging.
 
 
# Cryptographically secure randomness: QR identifiers must be unguessable,
# otherwise a student could forge a code without being in the room.
_secure_random = random.SystemRandom()
QR_IDENTIFIER_LENGTH = 32
QR_ALPHABET = string.ascii_letters + string.digits
 
 
# ---------------------------------------------------------------------------
# User profiles
# ---------------------------------------------------------------------------
 
class CourseProfile(models.Model):
    """Instructor-specific data, attached one-to-one to a Django User."""
 
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="instructor_profile"
    )
    department = models.CharField(max_length=100, blank=True)
    office = models.CharField(max_length=100, blank=True)
 
    class Meta:
        ordering = ["user__last_name", "user__first_name"]
 
    def __str__(self):
        return f"Instructor: {self.user.get_full_name() or self.user.username}"
 
 
class StudentProfile(models.Model):
    """Student-specific data, attached one-to-one to a Django User."""
 
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="student_profile"
    )
    student_number = models.CharField(
        max_length=32, unique=True,
        help_text="Institution-issued student ID.",
    )
 
    class Meta:
        ordering = ["user__last_name", "user__first_name"]
 
    def __str__(self):
        return f"Student: {self.user.get_full_name() or self.user.username} ({self.student_number})"
 
 
# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
 
class Course(models.Model):
    """A course taught by exactly one instructor."""
 
    code = models.CharField(max_length=20, help_text="e.g. CS101")
    name = models.CharField(max_length=200)
    term = models.CharField(max_length=20, help_text="e.g. Fall 2026")
    instructor = models.ForeignKey(
        CourseProfile, on_delete=models.PROTECT, related_name="courses"
    )
    students = models.ManyToManyField(
        StudentProfile, through="Enrollment", related_name="courses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["term", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "term"], name="unique_course_code_per_term"
            ),
        ]
 
    def __str__(self):
        return f"{self.code} — {self.name} ({self.term})"
 
 
# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
 
class Enrollment(models.Model):
    """Junction table: a student is enrolled in a course."""
 
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"], name="unique_enrollment"
            ),
        ]
 
    def __str__(self):
        return f"{self.student} → {self.course}"
 
 
# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
 
def generate_qr_identifier(length=QR_IDENTIFIER_LENGTH):
    """Return a random, unguessable string to be encoded in a lecture's QR code."""
    return "".join(_secure_random.choice(QR_ALPHABET) for _ in range(length))
 
 
class Lecture(models.Model):
    """A single class meeting.  Its QR code is only valid inside a time window."""
 
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="lectures"
    )
    title = models.CharField(max_length=200, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    qr_identifier = models.CharField(
        max_length=64, unique=True, editable=False, db_index=True,
        help_text="Random string encoded in this lecture's QR code.",
    )
    # Uploads are accepted from (start_time - grace) to (end_time + grace).
    grace_minutes = models.PositiveIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_time__gt=models.F("start_time")),
                name="lecture_end_after_start",
            ),
        ]
        indexes = [models.Index(fields=["course", "start_time"])]
 
    def save(self, *args, **kwargs):
        if not self.qr_identifier:
            # Retry on the (astronomically unlikely) collision.
            for _ in range(5):
                candidate = generate_qr_identifier()
                if not Lecture.objects.filter(qr_identifier=candidate).exists():
                    self.qr_identifier = candidate
                    break
            else:
                logger.error("Could not generate a unique QR identifier")
                raise RuntimeError("Could not generate a unique QR identifier")
        super().save(*args, **kwargs)
 
    def accepts_uploads_at(self, moment=None):
        """True if `moment` (default: now) is inside the allowed upload window."""
        moment = moment or timezone.now()
        grace = timezone.timedelta(minutes=self.grace_minutes)
        return (self.start_time - grace) <= moment <= (self.end_time + grace)
 
    def __str__(self):
        return f"{self.course.code} — {self.title or 'Lecture'} @ {self.start_time:%Y-%m-%d %H:%M}"
 
 
# ---------------------------------------------------------------------------
# QR Code Upload
# ---------------------------------------------------------------------------
 
class QRCodeUpload(models.Model):
    """A student's uploaded photo of a lecture's QR code.
 
    Anti-cheating fields:
      - decoded_value / lecture : the decoded QR must match the lecture.
      - image_sha256            : detects the same photo reused by many students.
      - uploaded_at             : checked against the lecture's time window.
      - status / reason         : audit trail of why an upload was rejected.
    """
 
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
 
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="qr_uploads"
    )
    lecture = models.ForeignKey(
        Lecture, on_delete=models.CASCADE, related_name="qr_uploads"
    )
    image = models.ImageField(upload_to="qr_uploads/%Y/%m/%d/")
    image_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    decoded_value = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    reason = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)
 
    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            # A student can retry after a rejection, but can only be
            # verified once per lecture.
            models.UniqueConstraint(
                fields=["student", "lecture"],
                condition=models.Q(status="verified"),
                name="one_verified_upload_per_student_lecture",
            ),
        ]
        indexes = [models.Index(fields=["lecture", "status"])]
 
    def __str__(self):
        return f"{self.student.student_number} → {self.lecture} [{self.status}]"
 
 
# ---------------------------------------------------------------------------
# Helper / API functions
# ---------------------------------------------------------------------------
 
def hash_uploaded_file(uploaded_file):
    """Return the SHA-256 hex digest of an uploaded file (used to catch reused photos)."""
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()
 
 
def is_enrolled(student, course):
    """True if `student` is enrolled in `course`."""
    return Enrollment.objects.filter(student=student, course=course).exists()
 
 
def record_upload(student, lecture, image_file, decoded_value=""):
    """Create a QRCodeUpload and validate it.  Returns the saved upload.
 
    Checks, in order: enrollment, time window, QR value matches the lecture,
    duplicate photo submitted by a different student, already verified.
    `decoded_value` is the text decoded from the image (decoding itself is
    done by the caller / a later step).
    """
    upload = QRCodeUpload(
        student=student,
        lecture=lecture,
        image=image_file,
        decoded_value=decoded_value,
        image_sha256=hash_uploaded_file(image_file),
    )
 
    def reject(reason):
        upload.status = QRCodeUpload.Status.REJECTED
        upload.reason = reason
        upload.save()
        logger.warning("Rejected upload by %s for %s: %s", student, lecture, reason)
        return upload
 
    if not is_enrolled(student, lecture.course):
        return reject("Student is not enrolled in this course.")
    if not lecture.accepts_uploads_at(upload.uploaded_at):
        return reject("Upload is outside the lecture's time window.")
    if decoded_value != lecture.qr_identifier:
        return reject("QR code does not match this lecture.")
    if (
        QRCodeUpload.objects.filter(image_sha256=upload.image_sha256)
        .exclude(student=student)
        .exists()
    ):
        return reject("This exact photo was already submitted by another student.")
    if QRCodeUpload.objects.filter(
        student=student, lecture=lecture, status=QRCodeUpload.Status.VERIFIED
    ).exists():
        return reject("Attendance already recorded for this lecture.")
 
    upload.status = QRCodeUpload.Status.VERIFIED
    upload.save()
    logger.info("Verified attendance: %s at %s", student, lecture)
    return upload
 
 
def get_attendees(lecture):
    """Students with a verified upload for `lecture`."""
    return StudentProfile.objects.filter(
        qr_uploads__lecture=lecture,
        qr_uploads__status=QRCodeUpload.Status.VERIFIED,
    ).distinct()
 
 
def get_absentees(lecture):
    """Enrolled students with no verified upload for `lecture`."""
    return (
        StudentProfile.objects.filter(enrollments__course=lecture.course)
        .exclude(pk__in=get_attendees(lecture).values("pk"))
        .distinct()
    )
 
 
def attendance_rate(student, course):
    """Fraction (0.0–1.0) of the course's past lectures the student attended."""
    past = course.lectures.filter(end_time__lte=timezone.now())
    total = past.count()
    if total == 0:
        return 0.0
    attended = (
        QRCodeUpload.objects.filter(
            student=student, lecture__in=past, status=QRCodeUpload.Status.VERIFIED
        )
        .values("lecture")
        .distinct()
        .count()
    )
    return attended / total