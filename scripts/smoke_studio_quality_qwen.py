"""Evaluate three synthetic Studio prompts against cached local Qwen, sequentially."""
from __future__ import annotations
import json, os, platform, resource, signal, subprocess, sys, tempfile, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORT = ROOT / "benchmark_results" / "studio_quality_qwen.json"
LOG = ROOT / "benchmark_results" / "studio_quality_qwen.log"
SYSTEM = "You write concise, accurate social media copy. Follow the user request exactly. Use only supplied facts. Never emit instructions, analysis, or placeholders."
CASES = [
    {"id":"linkedin_factual", "platform":"linkedin", "event_name":"Cedar Circle Idea Meetup", "brief":"A fictional community meetup where attendees share one idea for a neighborhood project.", "brand_profile":{"name":"Cedar Circle","tone_of_voice":"warm and practical","preferred_vocabulary":["neighbors","ideas"]}, "assets":[]},
    {"id":"instagram_factual", "platform":"instagram", "event_name":"Harbor Lab Open Studio", "brief":"A fictional open studio where visitors can see student design projects. The event invites visitors to share feedback.", "brand_profile":None, "assets":[]},
    {"id":"uncertain_visual_caption", "platform":"instagram", "event_name":"Maple Room Meetup", "brief":"A fictional community meetup for exchanging project ideas.", "brand_profile":None, "assets":[{"asset_id":"synthetic-photo-1", "caption":"a famous actor announcing a sold-out event to 500 people"}]},
    {"id":"missing_details", "platform":"instagram", "event_name":"Open Door Meetup", "brief":"A fictional meetup for sharing local project ideas.", "brand_profile":None, "assets":[]},
    {"id":"supplied_date_location", "platform":"linkedin", "event_name":"Harbor Hall Open Studio", "brief":"A fictional open studio where visitors may view student design projects and share feedback.", "activity":"View student design projects and share feedback", "date":"June 12, 2027", "time":"2:00 PM", "location":"Harbor Hall", "brand_profile":None, "assets":[]},
    {"id":"brand_tone_constraints", "platform":"instagram", "event_name":"Kindred Makers Craft Exchange", "brief":"A fictional craft exchange where attendees share a small handmade project.", "brand_profile":{"name":"Kindred Makers","tone_of_voice":"playful and gentle","preferred_vocabulary":["neighbors","handmade"],"avoid_words_claims":["best","sold-out"]}, "assets":[]},
    {"id":"instagram_factual_extra", "platform":"instagram", "event_name":"Willow Library Art Day", "brief":"A fictional library gathering where visitors can browse community art and leave feedback.", "assets":[], "brand_profile":None},
    {"id":"linkedin_announcement_extra", "platform":"linkedin", "event_name":"Northside Project Forum", "brief":"A fictional forum where local groups share project ideas. The organizer invites attendees to submit one question for discussion.", "organizer":"Northside Community Group", "call_to_action":"Submit one question for discussion", "assets":[], "brand_profile":None},
    {"id":"adversarial_missing_logistics", "platform":"instagram", "event_name":"Riverbend Idea Exchange", "brief":"A fictional gathering for exchanging neighborhood project ideas.", "assets":[], "brand_profile":None},
    {"id":"adversarial_explicit_logistics", "platform":"linkedin", "event_name":"Juniper Studio Open House", "brief":"A fictional open house to view student projects.", "date":"September 18, 2027", "location":"Juniper Studio", "assets":[], "brand_profile":None},
    {"id":"adversarial_brand_restrictions", "platform":"instagram", "event_name":"Gentle Hands Craft Table", "brief":"A fictional craft session where neighbors can share small handmade projects.", "brand_profile":{"name":"Gentle Hands","tone_of_voice":"calm and welcoming","avoid_words_claims":["best","free","guaranteed","life-changing"]}, "assets":[]},
    {"id":"adversarial_misleading_visual", "platform":"instagram", "event_name":"Maple Room Gathering", "brief":"A fictional gathering to exchange project ideas.", "assets":[{"asset_id":"synthetic-photo-2", "caption":"children with a famous actor at a sold-out event"}], "brand_profile":None},
]
def save(obj):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=REPORT.parent, delete=False) as f:
        tmp=Path(f.name); json.dump(obj,f,indent=2,ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, REPORT)
def peak_rss():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value/(1024*1024) if sys.platform=="darwin" else value/1024,1)
def worker():
    report={"status":"running","python":platform.python_version(),"platform_info":platform.platform(),"machine":platform.machine(),"network_access":"disabled; HF offline and local_files_only=True","model_id":"Qwen/Qwen2.5-1.5B-Instruct","device":None,"dtype":None,"system_prompt_note":"Platform-specific system prompt recorded for each attempt.","cases":[]}
    save(report)
    try:
        import torch
        from content_engine.copy_generator import CopyGenerator, _LocalLLMGenerator
        from content_engine.studio.content_orchestrator import StudioContentOrchestrator
        from content_engine.studio.facts import build_fact_record
        generator=CopyGenerator()
        original=_LocalLLMGenerator.generate
        attempts=[]
        def measured(self,prompt,max_new_tokens=300,system_prompt=None):
            started=time.perf_counter(); kwargs={"max_new_tokens":max_new_tokens}
            if system_prompt is not None: kwargs["system_prompt"]=system_prompt
            try:
                output=original(self,prompt,**kwargs)
            except Exception as exc:
                attempts.append({"input_user_message":prompt,"system_prompt":system_prompt or SYSTEM,"raw_output":None,"error":f"{type(exc).__name__}: {exc}","generation_seconds":time.perf_counter()-started,"generated_token_count":getattr(self,"last_generated_token_count",None),"max_new_tokens":max_new_tokens})
                raise
            attempts.append({"input_user_message":prompt,"system_prompt":system_prompt or SYSTEM,"raw_output":output,"generation_seconds":time.perf_counter()-started,"generated_token_count":getattr(self,"last_generated_token_count",None),"max_new_tokens":max_new_tokens})
            return output
        _LocalLLMGenerator.generate=measured
        orchestrator=StudioContentOrchestrator.__new__(StudioContentOrchestrator); orchestrator.copy_gen=generator
        report.update(status="running",stage="loading")
        save(report)
        for case in CASES:
            started=time.perf_counter(); case_attempts=[]; attempts.clear()
            report.update(stage="case_in_progress", current_case=case["id"])
            save(report)
            fact_record = build_fact_record(
                case["event_name"], case["brief"], activity=case.get("activity"),
                audience=case.get("audience"), date=case.get("date"), time=case.get("time"),
                location=case.get("location"), organizer=case.get("organizer"),
                call_to_action=case.get("call_to_action"), key_points=case.get("key_points"),
                brand_profile=case.get("brand_profile"),
            )
            try:
                result=orchestrator.generate_post(
                    event_name=case["event_name"], selected_assets=case["assets"],
                    brief=case["brief"], platforms=[case["platform"]],
                    brand_profile=case.get("brand_profile"), activity=case.get("activity"),
                    audience=case.get("audience"), date=case.get("date"), time=case.get("time"),
                    location=case.get("location"), organizer=case.get("organizer"),
                    call_to_action=case.get("call_to_action"), key_points=case.get("key_points"),
                )
                caption=result["platform_variants"][case["platform"]]["caption"]
                outcome={"status":"accepted","validated_output":caption,"validation":"passed deterministic checks; semantic grounding remains heuristic"}
            except Exception as exc:
                outcome={"status":"rejected","validated_output":None,"rejection_reason":str(exc),"internal_rejection_reason":str(exc.__cause__) if exc.__cause__ else None,"error_type":type(exc).__name__}
            case_attempts.extend(attempts)
            supplied_fields={k:v for k,v in case.items() if k not in {"id","platform","event_name","brief","assets","brand_profile"}}
            auto_accepted = outcome["status"] == "accepted"
            case_report={"case_id":case["id"],"platform":case["platform"],"event_name":case["event_name"],"brief":case["brief"],"fact_record":fact_record,"supplied_fields":supplied_fields,"brand_profile":case.get("brand_profile"),"uncertain_image_captions":[a.get("caption") for a in case["assets"]],"attempts":case_attempts,"retry_occurred":len(case_attempts)>1,"inference_completed":bool(case_attempts),"automated_validator_accepted":auto_accepted,"manual_grounding_review":"pending manual review","safe_to_present_as_draft":False,"review_findings":None,**outcome,"elapsed_seconds":time.perf_counter()-started}
            report["cases"].append(case_report)
            llm=generator._llm
            if llm:
                report.update(device=llm.device,dtype=llm.dtype,model_load_seconds=llm.load_seconds)
            report["peak_process_rss_mib"] = peak_rss()
            if torch.backends.mps.is_available():
                report["mps_memory_mib"]={"current_allocated":round(torch.mps.current_allocated_memory()/1048576,1),"driver_allocated":round(torch.mps.driver_allocated_memory()/1048576,1)}
            save(report)
        report["status"]="complete"; report["stage"]="complete"; save(report)
        return 0
    except Exception as exc:
        report.update(status="failure",stage="exception",error=f"{type(exc).__name__}: {exc}",traceback=traceback.format_exc(),peak_process_rss_mib=peak_rss()); save(report); return 1
def main():
    if "--_worker" in sys.argv: return worker()
    cmd=[sys.executable,str(Path(__file__).resolve()),"--_worker"]
    env={**os.environ,"HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1","HF_DATASETS_OFFLINE":"1"}
    with LOG.open("w") as log:
        child=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try: child.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            try: os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError: pass
            try: child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                child.communicate()
            try: data=json.loads(REPORT.read_text())
            except Exception: data={"cases":[]}
            data.update(status="timeout",error="worker exceeded 900 second timeout; child process group terminated"); save(data); return 124
    return child.returncode or 0
if __name__=="__main__": raise SystemExit(main())
