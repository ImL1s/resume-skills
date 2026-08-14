<!-- portable-resume-i18n: ar v0.4.4.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — دليل البدء السريع بالعربية

**الإصدار الحالي المنشور:** [`0.4.1`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.1)

ينقل Portable Resume سياقًا محليًا محدودًا من Claude وCodex وCursor وOpenCode وAntigravity وGrok وQwen وKimi إلى جلسة وكيل برمجي **جديدة**. لا يستعيد عملية أو جلسة عاملة. تعمل أدوات القراءة دون شبكة وبمكتبة Python القياسية فقط، ولا تشغّل CLI المصدر، وتوسم النص المستعاد بأنه خامل وغير موثوق.

## التثبيت

يتطلب Python 3.11+. ثبّت الحزمة المنشورة من PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
من checkout على `main` الحالي استخدم `pipx install .`. لتثبيت جميع host 18 في مسارات المستخدم العامة:

```bash
install-resume-skills quick-install all
```

لتثبيت Qwen للمشروع الحالي فقط:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

الوجهات المفعّلة على `main` هي Antigravity / agy وClaude Code وCline وCodex CLI / IDE وCrush وCursor Agent وGemini CLI وGitHub Copilot CLI وgoose وGrok Build وHermes Agent وKilo CLI وKimi Code CLI وOpenClaw وOpenCode وOpenHands وPi agent وQwen Code.
<!-- portable-resume-current-registry:end -->

إصدار `0.4.0` المنشور يشمل تسع وجهات مع Pi (تثبيت ملفات؛ الواجهة الأصلية not-run). راجع [دليل التثبيت](../install-hosts.md) لأوامر Skill وextension وplugin وmarketplace الدقيقة. افحص أي plugin وتحقق من SHA-256 الخاص بالـ release قبل منحه الثقة.

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

نتائج مستوى host هذه هي أدلة من حقبة v0.3.2. ما تزال إعادة تثبيت 0.4.1 لكل host ومسارات picker في حالة **not-run**.
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.4.1-host-reinstall-not-run -->

يوضح [حالة المشروع](../STATUS.md) الأدلة المثبتة وبوابات UI／release التي لم تُشغّل بعد.
