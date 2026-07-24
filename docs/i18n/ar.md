<!-- portable-resume-i18n: ar v0.3.1 -->
# Portable Resume — دليل البدء السريع بالعربية

ينقل Portable Resume سياقًا محليًا محدودًا من Claude وCodex وCursor وOpenCode وAntigravity وGrok وQwen وKimi إلى جلسة وكيل برمجي **جديدة**. لا يستعيد عملية أو جلسة عاملة. تعمل أدوات القراءة دون شبكة وبمكتبة Python القياسية فقط، ولا تشغّل CLI المصدر، وتوسم النص المستعاد بأنه خامل وغير موثوق.

## التثبيت

يتطلب Python 3.11+. ثبّت الحزمة المنشورة من PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

من checkout استخدم `pipx install .`. لتثبيت جميع host الثمانية في مسارات المستخدم العامة:

```bash
install-resume-skills quick-install all
```

لتثبيت Qwen للمشروع الحالي فقط:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

الوجهات هي Claude Code وCodex وCursor وOpenCode وAntigravity وGrok Build وQwen Code وKimi Code CLI. راجع [دليل التثبيت](../install-hosts.md) لأوامر Skill وextension وplugin وmarketplace الدقيقة. افحص أي plugin وتحقق من SHA-256 الخاص بالـ release قبل منحه الثقة.

## التحقق والاستخدام

داخل checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

فعّل `resume-<source>` بصيغة host الوجهة، وأعد فحص repository الحالي قبل تنفيذ handoff.

يوضح [حالة المشروع](../STATUS.md) الأدلة المثبتة وبوابات UI／release التي لم تُشغّل بعد.
