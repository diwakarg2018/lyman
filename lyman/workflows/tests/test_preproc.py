import os.path as op
import numpy as np
import pandas as pd
from scipy import signal
import nipype
import nibabel as nib

import pytest

from .. import preproc


class TestPreprocWorkflow(object):

    def save_image_frames(self, data_list, affine, fstem):

        n = len(data_list)
        filenames = ["{}{}.nii.gz".format(fstem, i) for i in range(n)]
        for frame, fname in zip(data_list, filenames):
            nib.save(nib.Nifti1Image(frame, affine), fname)
        return filenames

    def test_preproc_workflow_creation(self, lyman_info):

        proj_info = lyman_info["proj_info"]
        subjects = lyman_info["subjects"]
        sessions = lyman_info["sessions"]
        exp_info = lyman_info["exp_info"]

        wf = preproc.define_preproc_workflow(
            proj_info, exp_info, subjects, sessions,
        )

        # Check basic information about the workflow
        assert isinstance(wf, nipype.Workflow)
        assert wf.name == "preproc"
        assert wf.base_dir == op.join(proj_info.cache_dir, exp_info.name)

        # Check root directory of output
        template_out = wf.get_node("template_output")
        assert template_out.inputs.base_directory == proj_info.analysis_dir
        timeseries_out = wf.get_node("timeseries_output")
        assert timeseries_out.inputs.base_directory == proj_info.analysis_dir

        # Check the list of nodes we expect
        expected_nodes = ["subject_source", "session_source", "run_source",
                          "session_input", "run_input",
                          "estimate_distortions", "finalize_unwarping",
                          "transform_jacobian",
                          "fm2anat", "fm2anat_qc",
                          "sb2fm", "sb2fm_qc",
                          "ts2sb", "ts2sb_qc",
                          "combine_premats", "combine_postmats",
                          "restore_timeseries", "restore_template",
                          "finalize_timeseries", "finalize_template",
                          "template_output", "timeseries_output"]
        expected_nodes.sort()
        assert wf.list_node_names() == expected_nodes

    def test_preproc_iterables(self, lyman_info):

        proj_info = lyman_info["proj_info"]
        scan_info = proj_info["scan_info"]
        exp_info = lyman_info["exp_info"]

        # -- Test full iterables

        iterables = preproc.generate_iterables(
            scan_info, "exp_alpha", ["subj01", "subj02"],
        )
        expected_iterables = (
            ["subj01", "subj02"],
            {"subj01": [("subj01", "sess01"), ("subj01", "sess02")],
             "subj02": [("subj02", "sess01")]},
            {("subj01", "sess01"):
                [("subj01", "sess01", "run01"),
                 ("subj01", "sess01", "run02")],
             ("subj01", "sess02"):
                [("subj01", "sess02", "run01")],
             ("subj02", "sess01"):
                [("subj02", "sess01", "run01"),
                 ("subj02", "sess01", "run02"),
                 ("subj02", "sess01", "run03")]},
        )
        assert iterables == expected_iterables

        # -- Test iterables as set in workflow

        wf = preproc.define_preproc_workflow(
            proj_info, exp_info, ["subj01", "subj02"], None,
        )

        subject_source = wf.get_node("subject_source")
        assert subject_source.iterables == ("subject", iterables[0])

        session_source = wf.get_node("session_source")
        assert session_source.iterables == ("session", iterables[1])

        run_source = wf.get_node("run_source")
        assert run_source.iterables == ("run", iterables[2])

        # --  Test single subject

        iterables = preproc.generate_iterables(
            scan_info, "exp_alpha", ["subj01"],
        )
        expected_iterables = (
            ["subj01"],
            {"subj01": [("subj01", "sess01"), ("subj01", "sess02")]},
            {("subj01", "sess01"):
                [("subj01", "sess01", "run01"),
                 ("subj01", "sess01", "run02")],
             ("subj01", "sess02"):
                [("subj01", "sess02", "run01")]}
        )
        assert iterables == expected_iterables

        # -- Test different experiment

        iterables = preproc.generate_iterables(
            scan_info, "exp_beta", ["subj01", "subj02"],
        )
        expected_iterables = (
            ["subj01"],
            {"subj01": [("subj01", "sess02")]},
            {("subj01", "sess02"):
                [("subj01", "sess02", "run01"),
                 ("subj01", "sess02", "run02"),
                 ("subj01", "sess02", "run03")]},
        )
        assert iterables == expected_iterables

        # -- Test single subject, single session

        iterables = preproc.generate_iterables(
            scan_info, "exp_alpha", ["subj01"], ["sess02"],
        )
        expected_iterables = (
            ["subj01"],
            {"subj01": [("subj01", "sess02")]},
            {("subj01", "sess02"):
                [("subj01", "sess02", "run01")]},
        )
        assert iterables == expected_iterables

    def test_run_input(self, execdir, template):

        random_seed = sum(map(ord, "run_input"))
        rs = np.random.RandomState(random_seed)

        # --- Generate random test data

        subject = template["subject"]
        session, run = "sess01", "run01"
        run_tuple = subject, session, run
        exp_name = template["exp_info"].name
        sb_template = template["proj_info"].sb_template
        ts_template = template["proj_info"].ts_template
        crop_frames = 2

        affine = np.array([[-2, 0, 0, 10],
                           [0, -2, -1, 10],
                           [0, 1, 2, 5],
                           [0, 0, 0, 1]])

        func_dir = template["data_dir"].join(subject).join("func")

        shape = 12, 8, 4
        n_frames = 10

        keys = dict(experiment=exp_name, session=session, run=run)

        sb_data = rs.randint(10, 20, shape).astype(np.int16)
        sb_file = str(func_dir.join(sb_template.format(**keys)))
        nib.save(nib.Nifti1Image(sb_data, affine), sb_file)

        ts_data = rs.normal(10, 20, shape + (n_frames,))
        ts_file = str(func_dir.join(ts_template.format(**keys)))
        nib.save(nib.Nifti1Image(ts_data, affine), ts_file)

        # --- Run the interface

        res = preproc.RunInput(
            run=run_tuple,
            data_dir=template["data_dir"],
            analysis_dir=template["analysis_dir"],
            experiment=exp_name,
            sb_template=sb_template,
            ts_template=template["proj_info"].ts_template,
            crop_frames=crop_frames,
        ).run()

        # --- Test the outputs

        assert res.outputs.run_tuple == run_tuple
        assert res.outputs.subject == subject
        assert res.outputs.session == session
        assert res.outputs.run == run

        # Test outputs paths
        framedir = execdir.join("frames")
        ts_frames = [str(framedir.join("frame{:04d}.nii.gz".format(i)))
                     for i in range(n_frames - crop_frames)]

        assert res.outputs.ts_file == execdir.join("ts.nii.gz")
        assert res.outputs.sb_file == execdir.join("sb.nii.gz")
        assert res.outputs.ts_plot == execdir.join("raw.gif")
        assert res.outputs.ts_frames == ts_frames

        assert res.outputs.reg_file == template["reg_file"]
        assert res.outputs.seg_file == template["seg_file"]
        assert res.outputs.anat_file == template["anat_file"]
        assert res.outputs.mask_file == template["mask_file"]

        # Test the output timeseries
        std_affine = np.array([[2, 0, 0, -12],
                               [0, 2, -1, -4],
                               [0, -1, 2, 12],
                               [0, 0, 0, 1]])

        ts_img_out = nib.load(res.outputs.ts_file)

        assert np.array_equal(ts_img_out.affine, std_affine)
        assert ts_img_out.header.get_data_dtype() == np.dtype(np.float32)

        ts_data_out = ts_img_out.get_data()
        ts_data = ts_data[::-1, ::-1, :, crop_frames:].astype(np.float32)
        assert np.array_equal(ts_data_out, ts_data)

        for i, frame_fname in enumerate(res.outputs.ts_frames):
            frame_data = nib.load(frame_fname).get_data()
            assert np.array_equal(frame_data, ts_data[..., i])

        # Test that qc files exists
        assert op.exists(res.outputs.ts_plot)

    def test_session_input(self, execdir, template):

        random_seed = sum(map(ord, "session_input"))
        rs = np.random.RandomState(random_seed)

        subject = template["subject"]
        session = "sess01"
        session_tuple = subject, session

        fm_template = template["proj_info"].fm_template
        phase_encoding = template["proj_info"].phase_encoding

        func_dir = template["data_dir"].join(subject).join("func")

        shape = (12, 8, 4)
        n_frames = 3

        affine = np.array([[-2, 0, 0, 10],
                           [0, -2, -1, 10],
                           [0, 1, 2, 5],
                           [0, 0, 0, 1]])

        fieldmap_data = []
        fieldmap_files = []
        for encoding in [phase_encoding, phase_encoding[::-1]]:
            fm_keys = dict(session=session, encoding=encoding)
            fname = str(func_dir.join(fm_template.format(**fm_keys)))
            data = rs.randint(10, 25, shape + (n_frames,)).astype(np.int16)
            fieldmap_data.append(data)
            fieldmap_files.append(fname)
            nib.save(nib.Nifti1Image(data, affine), fname)

        # --- Run the interface

        res = preproc.SessionInput(
            session=session_tuple,
            data_dir=template["data_dir"],
            analysis_dir=template["analysis_dir"],
            fm_template=fm_template,
            phase_encoding=phase_encoding,
        ).run()

        # --- Test the outputs

        assert res.outputs.session_tuple == session_tuple
        assert res.outputs.subject == subject
        assert res.outputs.session == session

        # Test the output paths
        frame_template = "fieldmap_{:02d}.nii.gz"
        out_frames = [execdir.join(frame_template.format(i))
                      for i in range(n_frames * 2)]

        assert res.outputs.fm_file == execdir.join("fieldmap.nii.gz")
        assert res.outputs.fm_frames == out_frames

        assert res.outputs.reg_file == template["reg_file"]
        assert res.outputs.seg_file == template["seg_file"]
        assert res.outputs.anat_file == template["anat_file"]
        assert res.outputs.mask_file == template["mask_file"]

        # Test the output images
        std_affine = np.array([[2, 0, 0, -12],
                               [0, 2, -1, -4],
                               [0, -1, 2, 12],
                               [0, 0, 0, 1]])

        out_fm_img = nib.load(res.outputs.fm_file)
        assert np.array_equal(out_fm_img.affine, std_affine)

        fm_data = np.concatenate(fieldmap_data,
                                 axis=-1).astype(np.float32)[::-1, ::-1]
        fm_data_out = out_fm_img.get_data()
        assert np.array_equal(fm_data_out, fm_data)

        for i, frame in enumerate(out_frames):
            frame_data_out = nib.load(str(frame)).get_data()
            assert np.array_equal(frame_data_out, fm_data[..., i])

        # Test the output phase encoding information
        phase_encode_codes = ["y"] * n_frames + ["y-"] * n_frames
        assert res.outputs.phase_encoding == phase_encode_codes
        assert res.outputs.readout_times == [1] * (n_frames * 2)

        # Test reversed phase encoding
        phase_encoding = phase_encoding[::-1]
        res = preproc.SessionInput(
            session=session_tuple,
            data_dir=template["data_dir"],
            analysis_dir=template["analysis_dir"],
            fm_template=fm_template,
            phase_encoding=phase_encoding,
        ).run()

        # Test the output images
        fm_data = np.concatenate(fieldmap_data[::-1],
                                 axis=-1).astype(np.float32)[::-1, ::-1]
        fm_data_out = nib.load(res.outputs.fm_file).get_data()
        assert np.array_equal(fm_data_out, fm_data)

        for i, frame in enumerate(out_frames):
            frame_data_out = nib.load(str(frame)).get_data()
            assert np.array_equal(frame_data_out, fm_data[..., i])

    def test_combine_linear_transforms(self, execdir):

        a, b, c, d = np.random.randn(4, 4, 4)
        np.savetxt("ts2sb.mat", a)
        np.savetxt("sb2fm.mat", b)
        np.savetxt("fm2anat.mat", c)
        np.savetxt("anat2temp.mat", d)

        ab = np.dot(b, a)
        cd = np.dot(d, c)

        ifc = preproc.CombineLinearTransforms(ts2sb_file="ts2sb.mat",
                                              sb2fm_file="sb2fm.mat",
                                              fm2anat_file="fm2anat.mat",
                                              anat2temp_file="anat2temp.mat")

        res = ifc.run()

        assert np.loadtxt(res.outputs.ts2fm_file) == pytest.approx(ab)
        assert np.loadtxt(res.outputs.fm2temp_file) == pytest.approx(cd)

    def test_finalize_unwarping(self, execdir):

        # --- Generate random image data

        random_seed = sum(map(ord, "finalize_unwarping"))
        rs = np.random.RandomState(random_seed)
        shape = 12, 8, 4
        n_frames = 6
        shape_4d = shape + (n_frames,)
        affine = np.eye(4)
        affine[:3, :3] *= 2
        phase_encoding = ["y+"] * 3 + ["y-"] * 3

        raw_data = rs.uniform(0, 1, shape_4d)
        raw_file = "raw_frames.nii.gz"
        nib.save(nib.Nifti1Image(raw_data, affine), raw_file)

        corrected_data = rs.uniform(0, 10, shape_4d)
        corrected_file = "corrected_frames.nii.gz"
        nib.save(nib.Nifti1Image(corrected_data, affine), corrected_file)

        warp_shape = shape + (3,)
        warp_data = [rs.uniform(-8, 8, warp_shape) for _ in range(n_frames)]
        warp_files = self.save_image_frames(warp_data, affine, "warp")

        jacobian_data = [rs.uniform(.5, 1.5, shape) for _ in range(n_frames)]
        jacobian_files = self.save_image_frames(jacobian_data, affine, "jac")

        # --- Run the interface

        res = preproc.FinalizeUnwarping(
            raw_file=raw_file,
            corrected_file=corrected_file,
            warp_files=warp_files,
            jacobian_files=jacobian_files,
            phase_encoding=phase_encoding
        ).run()

        # --- Test outputs

        # Test output filenames
        assert res.outputs.raw_file == execdir.join("raw.nii.gz")
        assert res.outputs.corrected_file == execdir.join("func.nii.gz")
        assert res.outputs.warp_file == execdir.join("warp.nii.gz")
        assert res.outputs.mask_file == execdir.join("warp_mask.nii.gz")
        assert res.outputs.jacobian_file == execdir.join("jacobian.nii.gz")
        assert res.outputs.warp_plot == execdir.join("warp.png")
        assert res.outputs.unwarp_gif == execdir.join("unwarp.gif")

        # Test that the right frame of the raw image is selected
        raw_data_out = nib.load(res.outputs.raw_file).get_data()
        assert np.array_equal(raw_data_out, raw_data[..., 0])

        # Test that the corrected image is a temporal average
        jacobian_data = np.stack(jacobian_data, axis=-1)
        modulated_data = (corrected_data * jacobian_data).mean(axis=-1)
        corrected_data_out = nib.load(res.outputs.corrected_file).get_data()
        assert np.array_equal(corrected_data_out, modulated_data)

        # Test that the warp image has the right geometry
        warp_img_out = nib.load(res.outputs.warp_file)
        assert np.array_equal(warp_img_out.affine, affine)

        # Test that the warp image is the right frame
        warp_data_out = warp_img_out.get_data()
        assert np.array_equal(warp_data_out, warp_data[0])

        # Test the warp mask
        warp_mask = (np.abs(warp_data[0][..., 1]) < 4).astype(np.int)
        warp_mask_out = nib.load(res.outputs.mask_file).get_data()
        assert np.array_equal(warp_mask_out, warp_mask)

        # Test that the jacobians have same data but new geomtery
        jacobian_img_out = nib.load(res.outputs.jacobian_file)
        jacobian_data_out = jacobian_img_out.get_data()
        assert np.array_equal(jacobian_img_out.affine, affine)
        assert np.array_equal(jacobian_data_out, jacobian_data)

        # Test that qc plots exist
        assert op.exists(res.outputs.warp_plot)
        assert op.exists(res.outputs.unwarp_gif)

    def test_finalize_timeseries(self, execdir, template):

        # --- Generate input data

        experiment = "exp_alpha"
        run_tuple = subject, session, run = "subj01", "sess01", "run01"

        random_seed = sum(map(ord, "finalize_timeseries"))
        rs = np.random.RandomState(random_seed)
        shape = 12, 8, 4
        n_tp = 10
        affine = np.eye(4)
        affine[:3, :3] *= 2
        target = 10000

        fov = np.arange(np.product(shape)).reshape(shape) != 11
        in_data = [rs.normal(500, 10, shape) * fov for _ in range(n_tp)]
        in_files = self.save_image_frames(in_data, affine, "func")

        jacobian_data = rs.uniform(.5, 1.5, shape + (6,))
        jacobian_file = "jacobian.nii.gz"
        nib.save(nib.Nifti1Image(jacobian_data, affine), jacobian_file)

        mc_data = rs.normal(0, 1, (n_tp, 6))
        mc_file = "mc.txt"
        np.savetxt(mc_file, mc_data)

        # --- Run the interface

        res = preproc.FinalizeTimeseries(
            experiment=experiment,
            run_tuple=run_tuple,
            in_files=in_files,
            jacobian_file=jacobian_file,
            anat_file=template["anat_file"],
            seg_file=template["seg_file"],
            mask_file=template["mask_file"],
            mc_file=mc_file,
        ).run()

        # --- Test the outputs

        # Test output filenames
        assert res.outputs.out_file == execdir.join("func.nii.gz")
        assert res.outputs.out_gif == execdir.join("func.gif")
        assert res.outputs.out_png == execdir.join("func.png")
        assert res.outputs.mean_file == execdir.join("mean.nii.gz")
        assert res.outputs.mean_plot == execdir.join("mean.png")
        assert res.outputs.tsnr_file == execdir.join("tsnr.nii.gz")
        assert res.outputs.tsnr_plot == execdir.join("tsnr.png")
        assert res.outputs.mask_file == execdir.join("mask.nii.gz")
        assert res.outputs.mask_plot == execdir.join("mask.png")
        assert res.outputs.noise_file == execdir.join("noise.nii.gz")
        assert res.outputs.noise_plot == execdir.join("noise.png")
        assert res.outputs.mc_file == execdir.join("mc.csv")

        # Test the output path
        output_path = op.join(subject, experiment, "timeseries",
                              "{}_{}".format(session, run))
        assert res.outputs.output_path == output_path

        # Test the output timeseries
        out_img_out = nib.load(res.outputs.out_file)
        out_data_out = out_img_out.get_data()

        mask = nib.load(template["mask_file"]).get_data()
        func_mask = mask.astype(np.bool) & fov

        out_data = np.stack(in_data, axis=-1)
        out_data *= jacobian_data[..., [0]]
        out_data *= np.expand_dims(func_mask, -1)
        out_data *= target / out_data[func_mask].mean()
        mask_mean = out_data[func_mask].mean(axis=-1, keepdims=True)
        out_data[func_mask] = signal.detrend(out_data[func_mask]) + mask_mean

        assert np.array_equal(out_img_out.affine, affine)
        assert out_data_out == pytest.approx(out_data)
        assert out_data_out[func_mask].mean() == pytest.approx(target)

        # Test the output mask
        mask_data_out = nib.load(res.outputs.mask_file).get_data()
        assert np.array_equal(mask_data_out, func_mask.astype(np.float))

        # Test the output temporal statistics
        mean_out = nib.load(res.outputs.mean_file).get_data()
        tsnr_out = nib.load(res.outputs.tsnr_file).get_data()

        with np.errstate(all="ignore"):
            mean = out_data.mean(axis=-1)
            tsnr = mean / out_data.std(axis=-1)
            tsnr[~func_mask] = 0

        assert mean_out == pytest.approx(mean)
        assert tsnr_out == pytest.approx(tsnr)

        # Test the output motion correction data
        mc_cols = ["rot_x", "rot_y", "rot_z",
                   "trans_x", "trans_y", "trans_z"]
        mc_out = pd.read_csv(res.outputs.mc_file)
        assert mc_out.columns.tolist() == mc_cols
        assert mc_out.values == pytest.approx(mc_data)

        # Test that the qc files exist
        assert op.exists(res.outputs.out_gif)
        assert op.exists(res.outputs.out_png)
        assert op.exists(res.outputs.mean_plot)
        assert op.exists(res.outputs.tsnr_plot)
        assert op.exists(res.outputs.mask_plot)
        assert op.exists(res.outputs.noise_plot)

    def test_finalize_template(self, execdir, template):

        # --- Generate input data

        experiment = "exp_alpha"
        session_tuple = subject, session = "subj01", "sess01"

        random_seed = sum(map(ord, "finalize_template"))
        rs = np.random.RandomState(random_seed)
        shape = 12, 8, 4
        n_frames = 6
        n_runs = 4
        affine = np.eye(4)
        affine[:3, :3] *= 2
        target = 10000

        in_data = [rs.normal(500, 10, shape) for _ in range(n_frames)]
        in_files = self.save_image_frames(in_data, affine, "func")

        mask_data = [rs.choice([0, 1], shape, True, [.1, .9])
                     for _ in range(n_runs)]
        mask_files = self.save_image_frames(mask_data, affine, "mask")

        jacobian_data = rs.uniform(.5, 1.5, shape + (n_frames,))
        jacobian_file = "jacobian.nii.gz"
        nib.save(nib.Nifti1Image(jacobian_data, affine), jacobian_file)

        mean_data = [rs.normal(100, 5, shape) for _ in range(n_runs)]
        mean_files = self.save_image_frames(mean_data, affine, "mean")

        tsnr_data = [rs.normal(100, 5, shape) for _ in range(n_runs)]
        tsnr_files = self.save_image_frames(tsnr_data, affine, "tsnr")

        noise_data = [rs.choice([0, 1], shape, True, [.95, .05])
                      for _ in range(n_runs)]
        noise_files = self.save_image_frames(noise_data, affine, "noise")

        # --- Run the interface

        res = preproc.FinalizeTemplate(
            session_tuple=session_tuple,
            experiment=experiment,
            in_files=in_files,
            seg_file=template["seg_file"],
            anat_file=template["anat_file"],
            jacobian_file=jacobian_file,
            mask_files=mask_files,
            mean_files=mean_files,
            tsnr_files=tsnr_files,
            noise_files=noise_files,
        ).run()

        # --- Test the outputs

        # Test output filenames
        assert res.outputs.out_file == execdir.join("func.nii.gz")
        assert res.outputs.out_plot == execdir.join("func.png")
        assert res.outputs.mask_file == execdir.join("mask.nii.gz")
        assert res.outputs.mask_plot == execdir.join("mask.png")
        assert res.outputs.noise_file == execdir.join("noise.nii.gz")
        assert res.outputs.noise_plot == execdir.join("noise.png")
        assert res.outputs.mean_file == execdir.join("mean.nii.gz")
        assert res.outputs.mean_plot == execdir.join("mean.png")
        assert res.outputs.tsnr_file == execdir.join("tsnr.nii.gz")
        assert res.outputs.tsnr_plot == execdir.join("tsnr.png")

        # Test the output path
        output_path = op.join(subject, experiment, "template", session)
        assert res.outputs.output_path == output_path

        # Test the mask conjunction
        mask = np.all(mask_data, axis=0)
        mask_data_out = nib.load(res.outputs.mask_file).get_data()
        assert np.array_equal(mask_data_out, mask.astype(np.float))

        # Test the final template
        out_data_out = nib.load(res.outputs.out_file).get_data()

        out_data = np.stack(in_data, axis=-1) * jacobian_data
        out_data[mask] *= target / out_data[mask].mean(axis=0, keepdims=True)
        out_data = out_data.mean(axis=-1) * mask

        assert np.array_equal(out_data_out, out_data)

        # Test the noise mask union
        noise_data_out = nib.load(res.outputs.noise_file).get_data()
        noise_data = np.any(noise_data, axis=0).astype(np.float)
        assert np.array_equal(noise_data_out, noise_data)

        # Test the average mean image
        mean_data_out = nib.load(res.outputs.mean_file).get_data()
        mean_data = np.mean(mean_data, axis=0) * mask
        assert np.array_equal(mean_data_out, mean_data)

        # Test the average tsnr image
        tsnr_data_out = nib.load(res.outputs.tsnr_file).get_data()
        tsnr_data = np.mean(tsnr_data, axis=0) * mask
        assert np.array_equal(tsnr_data_out, tsnr_data)

        # Test that the qc images exist
        assert op.exists(res.outputs.out_plot)
        assert op.exists(res.outputs.mask_plot)
        assert op.exists(res.outputs.mean_plot)
        assert op.exists(res.outputs.tsnr_plot)
        assert op.exists(res.outputs.noise_plot)

    def test_realignment_report(self, execdir):

        target_data = np.random.uniform(0, 100, (12, 8, 4))
        target_file = "target.nii.gz"
        nib.save(nib.Nifti1Image(target_data, np.eye(4)), target_file)

        mc_data = np.random.normal(0, 1, (20, 6))
        mc_file = "mc.txt"
        np.savetxt(mc_file, mc_data)

        res = preproc.RealignmentReport(
            target_file=target_file,
            realign_params=mc_file
        ).run()

        assert res.outputs.params_plot == execdir.join("mc_params.png")
        assert res.outputs.target_plot == execdir.join("mc_target.png")

        assert op.exists(res.outputs.params_plot)
        assert op.exists(res.outputs.target_plot)

    def test_anat_reg_report(self, execdir):

        subject_id = "subj01"
        data_dir = execdir.mkdir("data")
        mri_dir = data_dir.mkdir(subject_id).mkdir("mri")

        shape = (12, 8, 4)
        affine = np.eye(4)

        cost_file = "cost.txt"
        cost_array = np.random.uniform(0, 1, 5)
        np.savetxt(cost_file, cost_array)

        in_data = np.random.normal(100, 5, shape)
        in_file = "func.nii.gz"
        nib.save(nib.Nifti1Image(in_data, affine), in_file)

        wm_data = np.random.randint(0, 2, shape).astype("uint8")
        wm_file = mri_dir.join("wm.mgz")
        nib.save(nib.MGHImage(wm_data, affine), str(wm_file))

        aseg_data = np.random.randint(0, 5, shape).astype("uint8")
        aseg_file = mri_dir.join("aseg.mgz")
        nib.save(nib.MGHImage(aseg_data, affine), str(aseg_file))

        res = preproc.AnatRegReport(
            subject_id=subject_id,
            data_dir=data_dir,
            in_file=in_file,
            cost_file=cost_file,
        ).run()

        assert res.outputs.out_file == execdir.join("reg.png")
        assert op.exists(res.outputs.out_file)

    def test_coreg_gif(self, execdir):

        in_data = np.random.uniform(0, 100, (12, 8, 4))
        in_file = "in.nii.gz"
        nib.save(nib.Nifti1Image(in_data, np.eye(4)), in_file)

        ref_data = np.random.uniform(0, 100, (12, 8, 4, 3))
        ref_file = "ref.nii.gz"
        nib.save(nib.Nifti1Image(ref_data, np.eye(4)), ref_file)

        out_file = "out.gif"

        res = preproc.CoregGIF(
            in_file=in_file,
            ref_file=ref_file,
            out_file=out_file,
        ).run()

        assert res.outputs.out_file == execdir.join(out_file)
        assert op.exists(out_file)
