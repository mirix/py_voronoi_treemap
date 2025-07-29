import os
import json
import subprocess
import tempfile
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
from math import sqrt
import array
import base64
from shapely.geometry import Polygon

def generate_js_script(path_data_json, path_output_json):
	return f"""
import fs from 'fs';
import * as d3 from 'd3';
import {{ voronoiTreemap }} from 'd3-voronoi-treemap';

function polygonRegular(radius, sides) {{
	const angleStep = 2 * Math.PI / sides;
	const points = [];
	for (let i = 0; i < sides; i++) {{
		let angle = i * angleStep;
		points.push([
			radius * Math.cos(angle),
			radius * Math.sin(angle)
		]);
	}}
	return points;
}}

try {{
	const raw = JSON.parse(fs.readFileSync("{path_data_json}"));
	const nested = d3.group(raw, d => d.Continent);

	const hierarchy = {{ name: "root", children: [] }};
	for (let [continent, countries] of nested) {{
		hierarchy.children.push({{
			name: continent,
			children: countries.map(d => ({{
				name: d.Country,
				value: d.Value
			}}))
		}});
	}}

	const root = d3.hierarchy(hierarchy).sum(d => d.value);
	const treemap = voronoiTreemap().clip(polygonRegular(1, 360));
	treemap(root);

	const out = [];
	root.each(d => {{
		if (d.polygon && d.data.name !== "root") {{
			out.push({{
				name: d.data.name,
				value: d.value,
				depth: d.depth,
				parent: d.parent.data.name,
				polygon: d.polygon
			}});
		}}
	}});
	fs.writeFileSync("{path_output_json}", JSON.stringify(out, null, 2));
}} catch (e) {{
	console.error(e);
	process.exit(1);
}}
"""

def run_voronoi_js(df):
	main_dir = os.path.dirname(os.path.abspath(__file__))

	with tempfile.TemporaryDirectory() as temp_dir:
		data_path = os.path.join(temp_dir, "data.json")
		output_path = os.path.join(temp_dir, "result.json")

		# Save JS script to the project root (not temp)
		js_path = os.path.join(main_dir, "generate.mjs")

		df[['Continent', 'Country', 'Value']].to_json(data_path, orient='records')

		with open(js_path, 'w') as f:
			f.write(generate_js_script(data_path, output_path))

		try:
			subprocess.run(["node", js_path], check=True, cwd=main_dir)
		finally:
			# Clean up JS file afterward
			os.remove(js_path)

		with open(output_path, 'r') as f:
			return json.load(f)

def svg_to_base64(file_path):
	with open(file_path, "rb") as image_file:
		encoded = base64.b64encode(image_file.read()).decode('utf-8')
	return "data:image/svg+xml;base64," + encoded

def plot_voronoi(polygons, df):
	country_polygons = [p for p in polygons if p['depth'] == 2]
	if not country_polygons:
		print("No country polygons found!")
		return

	fig = go.Figure()
	colors = px.colors.qualitative.G10
	total = sum(p['value'] for p in country_polygons)
	continents = {p['parent'] for p in country_polygons}
	color_map = {cont: colors[i % len(colors)] for i, cont in enumerate(continents)}

	base_dir = os.path.dirname(os.path.abspath(__file__))
	country_flag_map = df.set_index('Country')['Flag'].to_dict()

	processed_polygons = []
	for cell in country_polygons:
		points = [list(p) for p in cell['polygon']]
		poly = Polygon(points)
		centroid = poly.centroid
		area = poly.area

		processed_polygons.append({
			'cell': cell,
			'polygon': poly,
			'centroid': (centroid.x, centroid.y),
			'area': area
		})

	areas = [p['area'] for p in processed_polygons]
	min_area = min(areas) if areas else 0
	max_area = max(areas) if areas else 1

	for data in processed_polygons:
		cell = data['cell']
		poly = data['polygon']
		cx, cy = data['centroid']
		area = data['area']
		percentage = (cell['value'] / total) * 100

		x, y = poly.exterior.xy
		x = list(x)
		y = list(y)

		distance = sqrt(cx**2 + cy**2)
		if distance > 0.95:
			scale_factor = 1.0 - (distance - 0.9) * 1.5
			scale_factor = max(0.85, scale_factor)
			cx *= scale_factor
			cy *= scale_factor

		font_size = 10 + 6 * ((area - min_area) / (max_area - min_area))
		font_size = max(10, min(16, font_size))
		show_text = area >= min_area and distance <= 1
		hover_text = f"<b>{cell['name']}</b><br>{percentage:.1f}%"

		fig.add_trace(go.Scatter(
			x=x,
			y=y,
			fill='toself',
			mode='lines',
			line=dict(color='white', width=6),
			fillcolor=color_map[cell['parent']],
			name=hover_text,
			hoverinfo='text',
			hovertext=hover_text,
			showlegend=False
		))

		if show_text:
			flag_relative = country_flag_map.get(cell['name'])
			if flag_relative:
				flag_abs_path = os.path.join(base_dir, flag_relative)
				if os.path.exists(flag_abs_path):
					try:
						base64_svg = svg_to_base64(flag_abs_path)
						flag_size_px = 1.6 * font_size
						data_unit_per_pixel = 2.2 / 1024
						flag_size_data = flag_size_px * data_unit_per_pixel
						vertical_gap = flag_size_data * 1.2 # Data units above centroid
						horizontal_gap = flag_size_data

						# Add background marker (centered with flag)
						marker_size_data = flag_size_data * 600  # 1.6x flag size
						fig.add_trace(go.Scatter(
							x=[cx],
							y=[cy + vertical_gap],
							mode='markers',
							marker=dict(
								color='white',
								size=marker_size_data,  # Scale to data units
								sizemode='diameter'
							),
							showlegend=False,
							hoverinfo='skip'
						))

						# Add flag centered at (cx, cy + vertical_gap)
						fig.add_layout_image(
							dict(
								source=base64_svg,
								xref="x",
								yref="y",
								x=cx,
								y=cy + vertical_gap,
								sizex=flag_size_data,
								sizey=flag_size_data,
								xanchor="center",
								yanchor="middle",
								layer="above"
							)
						)
					except Exception as e:
						print(f"Error loading flag for {cell['name']}: {str(e)}")

			# Add text as annotations (centered relative to flag)
			fig.add_annotation(
				x=cx,
				y=cy,
				text=f"<b>{cell['name']}</b>",
				showarrow=False,
				font=dict(
					size=font_size * 1.1, 
					color='white', 
					family='Verdana, sans-serif',
					weight='bold'
				),
				xanchor='center',
				yanchor='middle'
			)
			fig.add_annotation(
				x=cx,
				y=cy - horizontal_gap,
				text=f"{percentage:.1f}%",
				showarrow=False,
				font=dict(
					size=font_size * 1.1, 
					color='white', 
					family='Courier New, monospace',
					weight='bold'
				),
				xanchor='center',
				yanchor='middle'
			)

	fig.update_layout(
		title=dict(
			text="Global GDP Distribution (2024)",
			x = 0.5,
			y = 0.99,
			xanchor='center',
			font=dict(size=24, weight='bold')
		),
		plot_bgcolor='white',
		xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor='y', range=[-1.1, 1.1]),
		yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-1.1, 1.1]),
		margin=dict(t=0, l=0, r=0, b=0),
		width=1024,
		height=1024,
		autosize=False,
	)
	fig.update_yaxes(scaleanchor="x", scaleratio=1)
	fig.write_html("voronoi_treemap_gdp_example.html")
	fig.show()

if __name__ == '__main__':
	base_dir = os.path.dirname(os.path.abspath(__file__))
	df = pd.read_csv(os.path.join(base_dir, 'gdp_2024.csv'))
	polygons = run_voronoi_js(df)
	plot_voronoi(polygons, df)
