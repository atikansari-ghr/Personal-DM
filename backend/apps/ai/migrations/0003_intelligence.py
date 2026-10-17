"""Change Set Z: AI Document Intelligence — Local/Cloud profiles with per-category send controls, AI Actions, provenance
and disposable AI outputs.

Existing profiles: an External endpoint becomes a Cloud profile. One that was already acknowledged keeps sending what it
sent before (OCR text and the metadata in the analysis prompt); original images and files stay off (they were never
sent). Existing jobs get their profile name / provider / location filled in from the profile.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def forwards(apps, schema_editor):
    Profile = apps.get_model("ai", "AIProfile")
    Job = apps.get_model("ai", "AIJob")
    for p in Profile.objects.all():
        cloud = p.privacy == "external"
        p.location = "cloud" if cloud else "local"
        if cloud and p.external_acknowledged:
            p.cloud_send_ocr_text = True
            p.cloud_send_metadata = True
        p.cloud_send_images = p.cloud_send_files = False
        p.save(update_fields=["location", "cloud_send_ocr_text", "cloud_send_metadata", "cloud_send_images", "cloud_send_files"])
        Job.objects.filter(profile=p).update(profile_name=p.name[:80], provider=p.provider, location=p.location)


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_analysis_stages"),
        ("library", "0012_doc_active_folder_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="aijob",
            name="data_sent",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="aijob",
            name="location",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="aijob",
            name="profile_name",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="aijob",
            name="provider",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="aijob",
            name="trigger",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="aijob",
            name="usage",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="aiprofile",
            name="cloud_send_files",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="aiprofile",
            name="cloud_send_images",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="aiprofile",
            name="cloud_send_metadata",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="aiprofile",
            name="cloud_send_ocr_text",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="aiprofile",
            name="last_test",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="aiprofile",
            name="location",
            field=models.CharField(default="local", max_length=10),
        ),
        migrations.AddField(
            model_name="aisuggestion",
            name="confidence",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aisuggestion",
            name="conflict",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="aisuggestion",
            name="evidence",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="aisuggestion",
            name="note",
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AlterField(
            model_name="aiprofile",
            name="provider",
            field=models.CharField(
                choices=[
                    (
                        "openai",
                        "Local LLM — OpenAI-compatible (LM Studio, llama.cpp, vLLM, LocalAI)",
                    ),
                    ("ollama", "Local LLM — Ollama"),
                    ("openai_cloud", "OpenAI"),
                    ("anthropic", "Anthropic Claude"),
                    ("gemini", "Google Gemini"),
                    ("openrouter", "OpenRouter"),
                ],
                default="openai",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="AIOutput",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("kind", models.CharField(max_length=10)),
                ("content", models.JSONField(default=dict)),
                ("question", models.CharField(blank=True, max_length=1000)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_outputs",
                        to="library.document",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="outputs",
                        to="ai.aijob",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
