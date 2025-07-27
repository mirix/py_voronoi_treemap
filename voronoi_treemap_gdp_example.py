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
from shapely.geometry import Polygon, Point

def generate_js_script(path_data_json, path_output_json, node_modules_path):
	return f"""
const fs = require("fs");
const path = require("path");

// Resolve modules using absolute path to node_modules
const d3 = Object.assign(
  {{}},
  require(path.join("{node_modules_path}", "d3")),
  require(path.join("{node_modules_path}", "d3-voronoi-treemap"))
);

// Define a regular polygon (approximate circle)
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
const treemap = d3.voronoiTreemap().clip(polygonRegular(1, 360));
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
"""

def run_voronoi_js(df):
	# Get the main script's directory where node_modules is located
	main_dir = os.path.dirname(os.path.abspath(__file__))
	node_modules_path = os.path.join(main_dir, "node_modules")
	
	with tempfile.TemporaryDirectory() as temp_dir:
		data_path = os.path.join(temp_dir, "data.json")
		output_path = os.path.join(temp_dir, "result.json")
		js_path = os.path.join(temp_dir, "generate.js")

		# Save data to temporary JSON file
		df[['Continent', 'Country', 'Value']].to_json(data_path, orient='records')

		# Write JS script to temporary file
		with open(js_path, 'w') as f:
			f.write(generate_js_script(data_path, output_path, node_modules_path))

		# Run Node.js from the main directory where node_modules is located
		subprocess.run(["node", js_path], check=True, cwd=main_dir)

		# Read and return results
		with open(output_path, 'r') as f:
			return json.load(f)

def plot_voronoi(polygons):
	# Filter only country-level polygons (depth=2)
	country_polygons = [p for p in polygons if p['depth'] == 2]
	
	if not country_polygons:
		print("No country polygons found!")
		return

	fig = go.Figure()
	colors = px.colors.qualitative.G10
	total = sum(p['value'] for p in country_polygons)
	continents = {p['parent'] for p in country_polygons}
	color_map = {cont: colors[i % len(colors)] for i, cont in enumerate(continents)}

	# Precompute all polygons and metrics
	processed_polygons = []
	for cell in country_polygons:
		# Convert to list if needed
		if isinstance(cell['polygon'][0], array.array):
			points = [list(p) for p in cell['polygon']]
		else:
			points = cell['polygon']
		
		# Create Shapely polygon
		poly = Polygon(points)
		centroid = poly.centroid
		area = poly.area
		
		processed_polygons.append({
			'cell': cell,
			'polygon': poly,
			'centroid': (centroid.x, centroid.y),
			'area': area
		})
	
	# Get area statistics
	areas = [p['area'] for p in processed_polygons]
	min_area = min(areas) if areas else 0
	max_area = max(areas) if areas else 1
	
	for data in processed_polygons:
		cell = data['cell']
		poly = data['polygon']
		cx, cy = data['centroid']
		area = data['area']
		percentage = (cell['value'] / total) * 100
		
		# Get polygon coordinates as lists
		x, y = poly.exterior.xy
		x = list(x)
		y = list(y)
		
		# Calculate distance from center
		distance = sqrt(cx**2 + cy**2)
		
		# Smoother adjustment for peripheral polygons
		# Only adjust when close to edge (distance > 0.9)
		if distance > 0.95:
			# Reduce adjustment amount: max 15% shift for outermost points
			# 0.9-1.0 distance maps to 1.0-0.85 scale factor
			scale_factor = 1.0 - (distance - 0.9) * 1.5
			scale_factor = max(0.85, scale_factor)
			cx *= scale_factor
			cy *= scale_factor
		
		# Determine font size
		font_size = 10 + 6 * ((area - min_area) / (max_area - min_area))
		font_size = max(10, min(16, font_size))
		
		# Only show text if polygon is large enough and not too close to edge
		#show_text = area > min_area * 2 and distance <= 0.98
		show_text = area >= min_area and distance <= 1
		
		# Format hover text to match labels: country name + percentage on new line
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
		
		# Add text label at centroid
		if show_text:
			fig.add_trace(go.Scatter(
				x=[cx],
				y=[cy],
				mode='text',
				text=[f"{cell['name']}"],
				textposition='middle center',
				textfont=dict(
					size=font_size * 1.1, 
					color='white', 
					weight='bold',
					family='Verdana, sans-serif'
				),
				showlegend=False,
				hoverinfo='skip'
			))
			fig.add_trace(go.Scatter(
				x=[cx],
				y=[cy - 0.03],
				mode='text',
				text=[f"{percentage:.1f}%"],
				textposition='middle center',
				textfont=dict(
					size=font_size * 1, 
					color='white', 
					weight='bold',
					family='Courier New, monospace'
				),
				showlegend=False,
				hoverinfo='skip'
			))

	# Layout configuration
	fig.update_layout(
		title=dict(
			text="Global GDP Distribution (2024)",
			x=0.5,
			xanchor='center',
			y=0.99,
			font=dict(size=24, family='Arial, sans-serif', weight='bold')
		),
		plot_bgcolor='white',
		xaxis=dict(
			showgrid=False,
			zeroline=False,
			showticklabels=False,
			scaleanchor='y',
			range=[-1.1, 1.1]
		),
		yaxis=dict(
			showgrid=False,
			zeroline=False,
			showticklabels=False,
			range=[-1.1, 1.1]
		),
		margin=dict(t=0, l=0, r=0, b=0),
		width=1024,
		height=1024,
		autosize=False,
	)
	fig.update_yaxes(scaleanchor="x", scaleratio=1)
	fig.write_html("voronoi_treemap_gdp_example.html")
	fig.show()

if __name__ == '__main__':
	df = pd.read_csv('gdp_2024.csv')
	polygons = run_voronoi_js(df)
	plot_voronoi(polygons)
