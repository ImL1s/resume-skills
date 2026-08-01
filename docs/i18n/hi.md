<!-- portable-resume-i18n: hi v0.4.0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — हिन्दी त्वरित शुरुआत

**वर्तमान प्रकाशित संस्करण:** [`0.4.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.0)

Portable Resume, Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen या Kimi के सीमित स्थानीय context को एक **नई** coding-agent session में ले जाता है। यह चलती process या session को restore नहीं करता। reader offline और केवल Python standard library पर चलता है, source CLI कभी नहीं चलाता, तथा मिले हुए text को inert और untrusted चिह्नित करता है।

## स्थापना

Python 3.11+ आवश्यक है। PyPI से प्रकाशित package स्थापित करें:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
वर्तमान `main` checkout से `pipx install .` उपयोग करें। सभी 18 destination host को user-global paths में स्थापित करने के लिए:

```bash
install-resume-skills quick-install all
```

केवल वर्तमान project में Qwen स्थापित करने के लिए:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

`main` पर सक्षम destination हैं Antigravity / agy, Claude Code, Cline, Codex CLI / IDE, Crush, Cursor Agent, Gemini CLI, GitHub Copilot CLI, goose, Grok Build, Hermes Agent, Kilo CLI, Kimi Code CLI, OpenClaw, OpenCode, OpenHands, Pi agent और Qwen Code।
<!-- portable-resume-current-registry:end -->

प्रकाशित `0.4.0` में Pi (filesystem install; native UI not-run) सहित नौ destinations हैं। सही direct Skill, extension, plugin और marketplace commands के लिए [installation guide](../install-hosts.md) देखें। किसी plugin पर भरोसा करने से पहले उसकी सामग्री और release SHA-256 जाँचें।

## सार्वजनिक marketplace

सार्वजनिक
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
छह संगत hosts के लिए native installation देता है:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

गाइड में Cursor, Qwen, Grok और Kimi के सत्यापित रास्ते तथा Antigravity／OpenCode के direct विकल्प दिए गए हैं।

## सत्यापन और उपयोग

checkout में चलाएँ:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

destination host की documented syntax से `resume-<source>` सक्रिय करें और handoff पर काम करने से पहले वर्तमान repository दोबारा जाँचें।

वर्तमान host smoke में 8/8 CLI invocation और 7/7 सटीक local native package installation सफल रहे। सार्वजनिक marketplace installation 6/6 संगत hosts पर सफल रहा; Cursor और Kimi marketplace picker भी सफल रहे। अन्य visual Skill picker और vendor-curated directories को पूर्ण होने का दावा नहीं किया गया है।

ये host-स्तरीय परिणाम v0.3.2 के समय के प्रमाण हैं। v0.4.0 के लिए प्रत्येक host पर पुनः इंस्टॉल और picker flow अभी भी **not-run** हैं।
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

सत्यापित दावों और अभी न चले UI／release gates के लिए [project status](../STATUS.md) देखें।
