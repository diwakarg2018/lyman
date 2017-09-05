import os.path as op
import nipype

from .. import model


class TestModelWorkflows(object):

    def test_model_fit_workflow_creation(self, lyman_info):

        proj_info = lyman_info["proj_info"]
        exp_info = lyman_info["exp_info"]
        model_info = lyman_info["model_info"]
        subjects = lyman_info["subjects"]
        sessions = lyman_info["sessions"]

        wf = model.define_model_fit_workflow(
            proj_info, exp_info, model_info, subjects, sessions,
        )

        # Check basic information about the workflow
        assert isinstance(wf, nipype.Workflow)
        assert wf.name == "model_fit"
        assert wf.base_dir == op.join(proj_info.cache_dir, exp_info.name)

        # Check root directory of output
        data_out = wf.get_node("data_output")
        assert data_out.inputs.base_directory == proj_info.analysis_dir

        # Check the list of nodes we expect
        expected_nodes = ["subject_source", "run_source",
                          "data_input", "fit_model", "data_output"]
        expected_nodes.sort()
        assert wf.list_node_names() == expected_nodes

    def test_model_results_workflow_creation(self, lyman_info):

        proj_info = lyman_info["proj_info"]
        exp_info = lyman_info["exp_info"]
        model_info = lyman_info["model_info"]
        subjects = lyman_info["subjects"]

        wf = model.define_model_results_workflow(
            proj_info, exp_info, model_info, subjects,
        )

        # Check basic information about the workflow
        assert isinstance(wf, nipype.Workflow)
        assert wf.name == "model_results"
        assert wf.base_dir == op.join(proj_info.cache_dir, exp_info.name)

        # Check root directory of output
        run_out = wf.get_node("run_output")
        assert run_out.inputs.base_directory == proj_info.analysis_dir
        subject_out = wf.get_node("subject_output")
        assert subject_out.inputs.base_directory == proj_info.analysis_dir

        # Check the list of nodes we expect
        expected_nodes = ["subject_source", "run_source", "data_input",
                          "estimate_contrasts", "model_results",
                          "run_output", "results_path", "subject_output"]
        expected_nodes.sort()
        assert wf.list_node_names() == expected_nodes

    def test_model_iterables(self, lyman_info):

        proj_info = lyman_info["proj_info"]
        scan_info = proj_info["scan_info"]
        exp_info = lyman_info["exp_info"]
        model_info = lyman_info["model_info"]

        # -- Test full iterables

        iterables = model.generate_iterables(
            scan_info, "exp_alpha", ["subj01", "subj02"],
        )
        expected_iterables = (
            ["subj01", "subj02"],
            {"subj01":
                [("sess01", "run01"),
                 ("sess01", "run02"),
                 ("sess02", "run01")],
             "subj02":
                [("sess01", "run01"),
                 ("sess01", "run02"),
                 ("sess01", "run03")]},
        )
        assert iterables == expected_iterables

        # -- Test iterables as set in workflow

        wf = model.define_model_fit_workflow(
            proj_info, exp_info, model_info, ["subj01", "subj02"], None,
        )

        subject_source = wf.get_node("subject_source")
        assert subject_source.iterables == ("subject", iterables[0])

        run_source = wf.get_node("run_source")
        assert run_source.iterables == ("run", iterables[1])

        wf = model.define_model_results_workflow(
            proj_info, exp_info, model_info, ["subj01", "subj02"],
        )

        subject_source = wf.get_node("subject_source")
        assert subject_source.iterables == ("subject", iterables[0])

        run_source = wf.get_node("run_source")
        assert run_source.iterables == ("run", iterables[1])

        # --  Test single subject

        iterables = model.generate_iterables(
            scan_info, "exp_alpha", ["subj01"],
        )
        expected_iterables = (
            ["subj01"],
            {"subj01":
                [("sess01", "run01"),
                 ("sess01", "run02"),
                 ("sess02", "run01")]}
        )
        assert iterables == expected_iterables

        # -- Test different experiment

        iterables = model.generate_iterables(
            scan_info, "exp_beta", ["subj01", "subj02"],
        )
        expected_iterables = (
            ["subj01"],
            {"subj01":
                [("sess02", "run01"),
                 ("sess02", "run02"),
                 ("sess02", "run03")]},
        )
        assert iterables == expected_iterables

        # -- Test single subject, single session

        iterables = model.generate_iterables(
            scan_info, "exp_alpha", ["subj01"], ["sess02"],
        )
        expected_iterables = (
            ["subj01"],
            {"subj01":
                [("sess02", "run01")]},
        )
        assert iterables == expected_iterables

    def test_model_results_path(self):

        analysis_dir = op.realpath(".")
        subject = "subj01"
        experiment = "exp_a"
        model_name = "model_alpha"

        ifc = model.ModelResultsPath(
            analysis_dir=analysis_dir,
            subject=subject,
            experiment=experiment,
            model=model_name,
        )

        res = ifc.run()
        expected_path = op.join(analysis_dir, subject,
                                experiment, model_name, "results")

        assert res.outputs.output_path == expected_path

    def test_model_fit_input(self, timeseries):

        subject = timeseries["subject"]
        run_tuple = session, run = timeseries["session"], timeseries["run"]

        exp_name = timeseries["exp_info"].name
        model_name = timeseries["model_info"].name

        res = model.ModelFitInput(
            experiment=exp_name,
            model=model_name,
            analysis_dir=str(timeseries["analysis_dir"]),
            subject=subject,
            run_tuple=run_tuple,
        ).run()

        assert res.outputs.subject == subject
        assert res.outputs.session == session
        assert res.outputs.run == run
        assert res.outputs.seg_file == timeseries["seg_file"]
        assert res.outputs.surf_file == timeseries["surf_file"]
        assert res.outputs.mask_file == timeseries["mask_file"]
        assert res.outputs.ts_file == timeseries["ts_file"]
        assert res.outputs.noise_file == timeseries["noise_file"]
        assert res.outputs.mc_file == timeseries["mc_file"]
        assert res.outputs.output_path == timeseries["model_dir"]

    def test_model_results_input(self, modelfit):

        subject = modelfit["subject"]
        run_tuple = session, run = modelfit["session"], modelfit["run"]

        exp_name = modelfit["exp_info"].name
        model_name = modelfit["model_info"].name

        res = model.ModelResultsInput(
            experiment=exp_name,
            model=model_name,
            analysis_dir=str(modelfit["analysis_dir"]),
            subject=subject,
            run_tuple=run_tuple,
        ).run()

        assert res.outputs.subject == subject
        assert res.outputs.session == session
        assert res.outputs.run == run
        assert res.outputs.anat_file == modelfit["anat_file"]
        assert res.outputs.mask_file == modelfit["mask_file"]
        assert res.outputs.beta_file == modelfit["beta_file"]
        assert res.outputs.ols_file == modelfit["ols_file"]
        assert res.outputs.error_file == modelfit["error_file"]
        assert res.outputs.output_path == modelfit["model_dir"]

    def test_model_fit(self, timeseries):

        pass
