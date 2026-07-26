<!-- portable-resume-i18n: ar v0.3.3 -->
# Portable Resume — دليل البدء السريع بالعربية

**الإصدار الحالي المنشور:** [`0.3.3`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.3)

ينقل Portable Resume سياقًا محليًا محدودًا من Claude وCodex وCursor وOpenCode وAntigravity وGrok وQwen وKimi إلى جلسة وكيل برمجي **جديدة**. لا يستعيد عملية أو جلسة عاملة. تعمل أدوات القراءة دون شبكة وبمكتبة Python القياسية فقط، ولا تشغّل CLI المصدر، وتوسم النص المستعاد بأنه خامل وغير موثوق.

## التثبيت

يتطلب Python 3.11+. ثبّت الحزمة المنشورة من PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

من checkout على `main` الحالي استخدم `pipx install .`. لتثبيت جميع host التسعة في مسارات المستخدم العامة:

```bash
install-resume-skills quick-install all
```

لتثبيت Qwen للمشروع الحالي فقط:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

الوجهات المفعّلة على `main` هي Claude Code وCodex وCursor وOpenCode وAntigravity وGrok Build وQwen Code وKimi Code CLI وPi (تثبيت ملفات فقط؛ واجهة المستخدم الأصلية not-run). إصدار `0.3.3` المنشور ما زال بثمانية وجهات. راجع [دليل التثبيت](../install-hosts.md) لأوامر Skill وextension وplugin وmarketplace الدقيقة. افحص أي plugin وتحقق من SHA-256 الخاص بالـ release قبل منحه الثقة.

## Marketplace عام

يوفر
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
العام تثبيتًا أصليًا لستة hosts متوافقة:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

يتضمن الدليل المسارات المتحقق منها لـ Cursor وQwen وGrok وKimi، إضافة إلى البدائل المباشرة لـ Antigravity وOpenCode.

## التحقق والاستخدام

داخل checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

فعّل `resume-<source>` بصيغة host الوجهة، وأعد فحص repository الحالي قبل تنفيذ handoff.

نجح اختبار host في 8/8 من استدعاءات CLI وفي 7/7 من عمليات تثبيت الحزم الأصلية المحلية الدقيقة. نجح التثبيت من marketplace العام على 6/6 من hosts المتوافقة، كما نجحت أدوات اختيار marketplace في Cursor وKimi. لا يُدّعى اكتمال أدوات اختيار Skill المرئية الأخرى أو الأدلة المنسقة من الموردين.

يوضح [حالة المشروع](../STATUS.md) الأدلة المثبتة وبوابات UI／release التي لم تُشغّل بعد.
