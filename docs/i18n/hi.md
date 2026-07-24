<!-- portable-resume-i18n: hi v0.3.0 -->
# Portable Resume — हिन्दी त्वरित शुरुआत

Portable Resume, Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen या Kimi के सीमित स्थानीय context को एक **नई** coding-agent session में ले जाता है। यह चलती process या session को restore नहीं करता। reader offline और केवल Python standard library पर चलता है, source CLI कभी नहीं चलाता, तथा मिले हुए text को inert और untrusted चिह्नित करता है।

## स्थापना

Python 3.11+ आवश्यक है। PyPI release के बाद:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

checkout से `pipx install .` उपयोग करें। सभी आठ destination host को user-global paths में स्थापित करने के लिए:

```bash
install-resume-skills quick-install all
```

केवल वर्तमान project में Qwen स्थापित करने के लिए:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

समर्थित destination हैं Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code और Kimi Code CLI। सही direct Skill, extension, plugin और marketplace commands के लिए [installation guide](../install-hosts.md) देखें। किसी plugin पर भरोसा करने से पहले उसकी सामग्री और release SHA-256 जाँचें।

## सत्यापन और उपयोग

checkout में चलाएँ:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

destination host की documented syntax से `resume-<source>` सक्रिय करें और handoff पर काम करने से पहले वर्तमान repository दोबारा जाँचें।

वैकल्पिक web search और Context7 [network integrations](../network-integrations.md) में हैं; reader स्वयं offline रहता है। सत्यापित दावों और अभी न चले UI／release gates के लिए [project status](../STATUS.md) देखें।
