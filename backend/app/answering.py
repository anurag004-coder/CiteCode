import re
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import quote

from .llm import generate_claims


def _citation(repository: Dict, chunk: Dict) -> Dict:
    source_type = chunk["source_type"]
    if source_type in {"issue", "commit"}:
        return {
            "path": chunk["path"],
            "symbol": chunk.get("symbol"),
            "start_line": None,
            "end_line": None,
            "commit_sha": chunk["commit_sha"],
            "source_type": source_type,
            "url": chunk.get("source_url", ""),
            "reference_key": chunk.get("reference_key"),
        }
    path = quote(chunk["path"], safe="/")
    source_url = "https://github.com/{}/{}/blob/{}/{}#L{}-L{}".format(
        quote(repository["owner"], safe=""),
        quote(repository["name"], safe=""),
        quote(chunk["commit_sha"], safe=""),
        path,
        chunk["start_line"],
        chunk["end_line"],
    )
    return {
        "path": chunk["path"],
        "symbol": chunk.get("symbol"),
        "start_line": chunk["start_line"],
        "end_line": chunk["end_line"],
        "commit_sha": chunk["commit_sha"],
        "source_type": source_type,
        "url": source_url,
        "reference_key": chunk.get("reference_key", chunk["path"]),
    }


def _evidence_source_text(item: Dict) -> str:
    if item.get("source_type") == "issue":
        return "{}\n{}".format(item.get("issue_title", ""), item.get("issue_body", ""))
    if item.get("source_type") == "commit":
        return str(item.get("commit_message", ""))
    return str(item.get("text", ""))


def _supporting_quote_is_valid(
    quote: str,
    evidence: List[Dict],
    source_verifier: Optional[Callable[[Dict, Optional[str]], bool]] = None,
) -> bool:
    normalized_quote = re.sub(r"\s+", " ", quote).strip().casefold()
    if len(normalized_quote) < 12:
        return False
    matched = False
    for item in evidence:
        normalized_source = re.sub(r"\s+", " ", _evidence_source_text(item)).strip().casefold()
        if normalized_quote in normalized_source:
            matched = True
            break
    if not matched:
        return False
    if source_verifier is None:
        return True
    return (
        all(source_verifier(item, None) for item in evidence)
        and any(source_verifier(item, quote) for item in evidence)
    )


REFUSAL_TEXT = {
    "English": "I can't answer this from the indexed repository because there is not enough supporting evidence.",
    "Hindi": "पर्याप्त सहायक साक्ष्य न होने के कारण मैं अनुक्रमित रिपॉज़िटरी से इसका उत्तर नहीं दे सकता।",
    "Bengali": "যথেষ্ট সহায়ক প্রমাণ না থাকায় আমি সূচিবদ্ধ রিপোজিটরি থেকে এর উত্তর দিতে পারছি না।",
    "Spanish": "No puedo responder esto a partir del repositorio indexado porque no hay suficiente evidencia de respaldo.",
    "French": "Je ne peux pas répondre à partir du dépôt indexé, car les éléments justificatifs sont insuffisants.",
    "German": "Ich kann diese Frage anhand des indizierten Repositorys nicht beantworten, da die Belege nicht ausreichen.",
    "Portuguese": "Não posso responder com base no repositório indexado porque não há evidências suficientes.",
    "Japanese": "裏付けとなる証拠が十分でないため、インデックス済みリポジトリからこの質問には回答できません。",
    "Chinese": "由于缺少足够的支持证据，我无法根据已索引的代码库回答这个问题。",
}

EXTRACTIVE_TEXT = {
    "English": "A generated answer is unavailable, so these are source excerpts rather than an AI explanation.",
    "Hindi": "जनरेट किया गया उत्तर उपलब्ध नहीं है, इसलिए ये AI व्याख्या के बजाय स्रोत से लिए गए अंश हैं।",
    "Bengali": "তৈরি করা উত্তর পাওয়া যাচ্ছে না, তাই এগুলো AI ব্যাখ্যার বদলে উৎস থেকে নেওয়া অংশ।",
    "Spanish": "La respuesta generada no está disponible; estos son fragmentos de las fuentes, no una explicación de IA.",
    "French": "La réponse générée n’est pas disponible ; voici des extraits des sources plutôt qu’une explication par IA.",
    "German": "Eine generierte Antwort ist nicht verfügbar. Daher folgen Quellenauszüge statt einer KI-Erklärung.",
    "Portuguese": "A resposta gerada não está disponível; estes são trechos das fontes, não uma explicação de IA.",
    "Japanese": "生成された回答を利用できないため、AIによる説明ではなくソースからの抜粋を示します。",
    "Chinese": "目前无法生成回答，以下提供的是源代码摘录，而非 AI 解释。",
}


def _verification_note(language: str, source_records: bool, assumption: bool = False) -> str:
    notes = {
        "English": {
            "record": "The cited quote matched the live GitHub issue or commit. Interpretation still needs human judgment.",
            "source": "The cited quote matched the file lines at the indexed GitHub commit. Interpretation still needs human judgment.",
            "assumption": "The model marked this as an inference rather than a repository fact.",
            "excerpt": "Exact repository excerpt; no model paraphrase was generated.",
        },
        "Hindi": {
            "record": "उद्धृत अंश GitHub के लाइव issue या commit से मेल खाया; अर्थ की पुष्टि के लिए मानवीय निर्णय आवश्यक है।",
            "source": "उद्धृत अंश इंडेक्स किए गए GitHub commit की फ़ाइल पंक्तियों से मेल खाया; अर्थ की पुष्टि के लिए मानवीय निर्णय आवश्यक है।",
            "assumption": "मॉडल ने इसे रिपॉज़िटरी तथ्य के बजाय अनुमान के रूप में चिह्नित किया।",
            "excerpt": "रिपॉज़िटरी से लिया गया हूबहू अंश; मॉडल ने इसे दोबारा नहीं लिखा।",
        },
        "Bengali": {
            "record": "উদ্ধৃত অংশটি GitHub-এর বর্তমান issue বা commit-এর সঙ্গে মিলেছে; ব্যাখ্যার জন্য মানুষের বিচার প্রয়োজন।",
            "source": "উদ্ধৃত অংশটি ইনডেক্স করা GitHub commit-এর ফাইল লাইনের সঙ্গে মিলেছে; ব্যাখ্যার জন্য মানুষের বিচার প্রয়োজন।",
            "assumption": "মডেল এটিকে রিপোজিটরির তথ্য নয়, অনুমান হিসেবে চিহ্নিত করেছে।",
            "excerpt": "রিপোজিটরি থেকে হুবহু নেওয়া অংশ; মডেল এটি নতুন করে লেখেনি।",
        },
        "Spanish": {
            "record": "La cita coincide con el issue o commit actual de GitHub; la interpretación aún requiere criterio humano.",
            "source": "La cita coincide con las líneas del archivo en el commit indexado de GitHub; la interpretación aún requiere criterio humano.",
            "assumption": "El modelo marcó esto como una inferencia, no como un hecho del repositorio.",
            "excerpt": "Fragmento exacto del repositorio; el modelo no lo parafraseó.",
        },
        "French": {
            "record": "La citation correspond à l’issue ou au commit GitHub actuel ; l’interprétation reste à valider par une personne.",
            "source": "La citation correspond aux lignes du fichier dans le commit GitHub indexé ; l’interprétation reste à valider par une personne.",
            "assumption": "Le modèle a indiqué qu’il s’agissait d’une déduction et non d’un fait du dépôt.",
            "excerpt": "Extrait exact du dépôt ; le modèle ne l’a pas reformulé.",
        },
        "German": {
            "record": "Das Zitat stimmt mit dem aktuellen GitHub-Issue oder Commit überein. Die Interpretation muss weiterhin menschlich beurteilt werden.",
            "source": "Das Zitat stimmt mit den Dateizeilen im indexierten GitHub-Commit überein. Die Interpretation muss weiterhin menschlich beurteilt werden.",
            "assumption": "Das Modell hat dies als Schlussfolgerung und nicht als Repository-Fakt markiert.",
            "excerpt": "Exakter Repository-Auszug; das Modell hat ihn nicht umformuliert.",
        },
        "Portuguese": {
            "record": "A citação corresponde à issue ou ao commit atual do GitHub; a interpretação ainda exige avaliação humana.",
            "source": "A citação corresponde às linhas do arquivo no commit indexado do GitHub; a interpretação ainda exige avaliação humana.",
            "assumption": "O modelo marcou isto como uma inferência, não como um fato do repositório.",
            "excerpt": "Trecho exato do repositório; o modelo não o parafraseou.",
        },
        "Japanese": {
            "record": "引用文がGitHub上のissueまたはcommitと一致しました。解釈には引き続き人の判断が必要です。",
            "source": "引用文がインデックス済みGitHub commitのファイル行と一致しました。解釈には引き続き人の判断が必要です。",
            "assumption": "モデルはこれをリポジトリの事実ではなく推論として示しました。",
            "excerpt": "リポジトリからの正確な抜粋です。モデルによる言い換えはありません。",
        },
        "Chinese": {
            "record": "引用内容与 GitHub 上的 issue 或 commit 相匹配；解释仍需人工判断。",
            "source": "引用内容与索引的 GitHub 提交中的文件行相匹配；解释仍需人工判断。",
            "assumption": "模型将此标记为推断，而非代码库事实。",
            "excerpt": "代码库中的原文摘录；模型没有改写。",
        },
    }
    text = notes.get(language, notes["English"])
    if assumption:
        return text["assumption"]
    return text["record" if source_records else "source"]


def _refusal(question: str, evidence: List[Dict], reason: str, language: str = "English") -> Dict:
    paths = []
    for item in evidence:
        if item["path"] not in paths:
            paths.append(item["path"])
    return {
        "mode": "refusal",
        "answer": REFUSAL_TEXT.get(language, REFUSAL_TEXT["English"]),
        "claims": [],
        "refusal_reason": reason,
        "searched_paths": paths,
    }


def answer_question(
    question: str,
    repository: Dict,
    retrieved: List[Dict],
    sufficient: bool,
    explanation_language: str = "English",
    source_verifier: Optional[Callable[[Dict, Optional[str]], bool]] = None,
    include_diagnostics: bool = False,
) -> Dict:
    diagnostics = {
        "generation_performed": False,
        "generated_fact_claims": 0,
        "source_checked_fact_claims": 0,
        "rejected_fact_claims": 0,
    }

    def finish(result: Dict) -> Dict:
        if include_diagnostics:
            result["_quality_diagnostics"] = dict(diagnostics)
        return result

    if not sufficient:
        return finish(_refusal(
            question, retrieved, "Retrieval did not find enough matching repository evidence.",
            explanation_language,
        ))

    evidence = []
    for index, item in enumerate(retrieved, start=1):
        row = dict(item)
        row["evidence_id"] = "E{}".format(index)
        evidence.append(row)

    generated = generate_claims(question, evidence, explanation_language)
    if generated is None:
        # Keep the API useful without a configured model. These are exact source excerpts,
        # not AI-generated explanations.
        claims = []
        for item in evidence[:3]:
            excerpt = _evidence_source_text(item).strip()
            if len(excerpt) > 700:
                excerpt = excerpt[:697].rstrip() + "..."
            if source_verifier and not _supporting_quote_is_valid(excerpt, [item], source_verifier):
                continue
            claims.append(
                {
                    "text": excerpt,
                    "status": "source_checked",
                    "verification_note": _verification_note(explanation_language, False),
                    "citations": [_citation(repository, item)],
                }
            )
        if not claims:
            return finish(_refusal(
                question, evidence, "Live GitHub sources could not confirm the retrieved excerpts.",
                explanation_language,
            ))
        return finish({
            "mode": "extractive",
            "answer": EXTRACTIVE_TEXT.get(explanation_language, EXTRACTIVE_TEXT["English"]),
            "claims": claims,
            "refusal_reason": None,
            "searched_paths": list(dict.fromkeys(item["path"] for item in evidence)),
        })

    valid_by_id = {item["evidence_id"]: item for item in evidence}
    diagnostics["generation_performed"] = True
    generated_claims = generated.get("claims", [])
    if not isinstance(generated_claims, list):
        generated_claims = []
    diagnostics["generated_fact_claims"] = sum(
        1 for item in generated_claims
        if isinstance(item, dict)
        and str(item.get("text", "")).strip()
        and str(item.get("label", "FROM_CODE")).upper() == "FROM_CODE"
    )
    if generated.get("not_enough_evidence") is True:
        diagnostics["rejected_fact_claims"] = diagnostics["generated_fact_claims"]
        return finish(_refusal(
            question, evidence, "The answer model judged the retrieved evidence insufficient.",
            explanation_language,
        ))

    claims = []
    for item in generated_claims:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        supporting_quote = str(item.get("evidence_quote", "")).strip()
        raw_ids = item.get("evidence_ids", [])
        if not isinstance(raw_ids, list):
            raw_ids = []
        cited = []
        seen: Set[str] = set()
        for evidence_id in raw_ids:
            evidence_id = str(evidence_id)
            if evidence_id in valid_by_id and evidence_id not in seen:
                cited.append(valid_by_id[evidence_id])
                seen.add(evidence_id)

        label = str(item.get("label", "FROM_CODE")).upper()
        if label == "FROM_CODE" and cited and _supporting_quote_is_valid(
            supporting_quote, cited, source_verifier
        ):
            status = "source_checked"
            diagnostics["source_checked_fact_claims"] += 1
            source_records = any(source.get("source_type") in {"issue", "commit"} for source in cited)
            note = _verification_note(explanation_language, source_records)
        elif label == "ASSUMPTION":
            status = "assumption"
            note = _verification_note(explanation_language, False, assumption=True)
        else:
            # Do not present a repository statement as verified if its evidence id or
            # exact supporting excerpt did not survive application checks.
            continue

        claims.append(
            {
                "text": text,
                "status": status,
                "verification_note": note,
                "citations": [_citation(repository, source) for source in cited],
            }
        )

    if not claims:
        diagnostics["rejected_fact_claims"] = diagnostics["generated_fact_claims"]
        return finish(_refusal(
            question, evidence, "No generated claim passed the source checks.", explanation_language
        ))
    diagnostics["rejected_fact_claims"] = max(
        0, diagnostics["generated_fact_claims"] - diagnostics["source_checked_fact_claims"]
    )
    return finish({
        "mode": "generated",
        "answer": " ".join(claim["text"] for claim in claims),
        "claims": claims,
        "refusal_reason": None,
        "searched_paths": list(dict.fromkeys(item["path"] for item in evidence)),
    })
