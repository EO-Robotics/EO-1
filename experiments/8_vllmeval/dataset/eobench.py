import re

import pandas as pd

from ..smp import *
from .image_base import ImageBaseDataset


class EOBench(ImageBaseDataset):
    TYPE = "MCQ"

    def __init__(self, dataset="EOBench", data_file=None, data_root=None, skip_noimg=True):
        ROOT = LMUDataRoot()
        # You can override this variable to save image files to a different directory
        self.dataset_name = dataset
        self.data_file = data_file
        self.data_root = data_root

        data = self.load_data(dataset, data_file, data_root)

        self.skip_noimg = skip_noimg
        if skip_noimg and "image" in data:
            data = data[~pd.isna(data["image"])]
        self.meta_only = True

        # the dataframe has `id` field, which is the index
        data["index"] = data["id"]

        self.data = data
        self.post_build(dataset)

    def load_data(self, dataset="EOBench", data_file=None, data_root=None):
        def load_jsonl(f):
            lines = open(f, encoding="utf-8").readlines()
            lines = [x.strip() for x in lines]
            if lines[-1] == "":
                lines = lines[:-1]
            data = [json.loads(x) for x in lines]
            return pd.DataFrame(data)

        data = load_jsonl(data_file)
        return data

    def build_prompt(self, line):
        if isinstance(line, int):
            line = self.data.iloc[line]

        if self.meta_only:
            tgt_path = toliststr(line["image_paths"])
            tgt_path = [osp.join(self.data_root, p) for p in tgt_path]
        else:
            tgt_path = self.dump_image(line)

        prompt = line["question"]
        msgs = []
        if isinstance(tgt_path, list):
            msgs.extend([dict(type="image", value=p) for p in tgt_path])
        else:
            msgs = [dict(type="image", value=tgt_path)]
        msgs.append(dict(type="text", value=prompt))

        return msgs

    @staticmethod
    def extract_characters_regex(s, choices=["(A)", "(B)", "(C)", "(D)", "(E)", "(F)", "(G)"]):
        if type(s) is dict:
            s = ""
        s = s.strip()
        answer_prefixes = [
            "The best answer is",
            "The correct answer is",
            "The answer is",
            "The answer",
            "The best option isThe correct option is",
            "Best answer:Best option:",
        ]
        for answer_prefix in answer_prefixes:
            s = s.replace(answer_prefix, "")

        if not re.search("[ABCDEFG]", s):
            return ""
        matches = re.findall(r"\(([a-gA-G])\)", s)
        if len(matches) == 0:
            matches = re.findall(r"(?:^|\s)?([a-gA-G])(?:$|[\s,.])?", s)
        if len(matches) == 0:
            matches = re.findall(r"[a-gA-G]", s)
        if len(matches) == 0:
            return ""
        else:
            matches = {mat.upper() for mat in matches}
            return "".join(matches)

    def evaluate(self, eval_file, **judge_kwargs):
        data = load(eval_file)
        data["prediction"] = [str(x) for x in data["prediction"]]
        task_stats = {}
        micro_metric = {"correct": 0, "total": 0}
        for index, it in data.iterrows():
            task = it.get("question_type", "unknown")
            if task not in task_stats:
                task_stats[task] = {"correct": 0, "total": 0}
            task_stats[task]["total"] += 1
            micro_metric["total"] += 1
            pred = self.extract_characters_regex(it["prediction"])

            if set(pred) == set(it["answer"]):
                task_stats[task]["correct"] += 1
                micro_metric["correct"] += 1

            elif set(pred).issubset(it["answer"]):
                task_stats[task]["correct"] += len(set(pred)) / len(it["answer"])
                micro_metric["correct"] += len(set(pred)) / len(it["answer"])

        accuracy_dict = {
            task: [stats["correct"] / stats["total"]] for task, stats in sorted(task_stats.items())
        }
        result_df = pd.DataFrame(accuracy_dict)
        from collections import defaultdict

        sphere_accs = defaultdict(list)
        for task, acc in accuracy_dict.items():
            sphere = task.split("/")[0]
            assert len(acc) == 1
            sphere_accs[sphere].append(acc[0])
        for sphere, accs in sphere_accs.items():
            result_df[f"Sphere macro: {sphere}"] = sum(accs) / len(accs)
        result_df["Overall macro"] = result_df.mean(axis=1)
        result_df["Overall micro"] = micro_metric["correct"] / micro_metric["total"]
        suffix = eval_file.split(".")[-1]
        score_file = eval_file.replace(f".{suffix}", "_acc.csv")
        dump(result_df, score_file)
        return result_df
